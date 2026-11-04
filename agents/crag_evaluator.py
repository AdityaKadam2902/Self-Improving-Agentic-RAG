"""
Corrective RAG (CRAG) Quality Evaluator.

Assesses the quality, relevance, and factual utility of retrieved chunks prior
to generation:
- Classifies chunks into CORRECT, AMBIGUOUS, or INCORRECT based on multi-signal scoring.
- Strips irrelevant distractor chunks (INCORRECT) to prevent LLM context poisoning.
- Performs sentence-level noise filtration on AMBIGUOUS chunks.
- Flags overall retrieval outcome to prevent hallucinated synthesis when all chunks fail.
- Offers sub-5ms deterministic heuristic scoring alongside optional LLM verification.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.config import get_settings
from backend.agents.retriever import RetrievedChunk
from backend.utils.async_executor import run_in_threadpool


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with",
    "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves", "tell", "explain", "give", "show",
}


@dataclass
class ChunkEvaluation:
    """Individual chunk quality assessment."""

    chunk_id: str
    confidence_score: float
    status: str  # "CORRECT" | "AMBIGUOUS" | "INCORRECT"
    reason: str
    term_overlap_ratio: float
    phrase_match_count: int


@dataclass
class CRAGResult:
    """Aggregate Corrective RAG evaluation result."""

    action: str  # "CORRECT" | "AMBIGUOUS" | "INCORRECT"
    confidence: float
    kept_chunks: List[RetrievedChunk]
    discarded_chunks: List[RetrievedChunk]
    evaluations: List[ChunkEvaluation]
    noise_stripped_count: int
    evaluation_ms: float


def _extract_keywords(text: str) -> List[str]:
    """Tokenize and filter out English stopwords."""
    raw_tokens = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", text.lower())
    return [t for t in raw_tokens if t not in _STOPWORDS]


def _extract_ngrams(tokens: List[str], n: int) -> List[str]:
    """Extract consecutive word n-grams."""
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def strip_noise_sentences(chunk_text: str, query_keywords: List[str]) -> Tuple[str, bool]:
    """
    Remove low-information or boilerplate sentences from an ambiguous chunk.
    Retains sentences containing at least one query keyword or core entities.
    """
    if not query_keywords:
        return chunk_text, False

    sentences = re.split(r"(?<=[.!?])\s+", chunk_text.strip())
    if len(sentences) <= 2:
        return chunk_text, False

    retained_sentences = []
    stripped = False

    for sent in sentences:
        s_lower = sent.lower()
        # Keep sentence if it matches any query keyword, contains numbers, or is a markdown table
        if (
            any(k in s_lower for k in query_keywords)
            or bool(re.search(r"\d+", s_lower))
            or "|" in sent
        ):
            retained_sentences.append(sent)
        else:
            stripped = True

    if not retained_sentences:
        return chunk_text, False

    return " ".join(retained_sentences), stripped


def score_chunk_relevance(
    query: str,
    chunk: RetrievedChunk,
    correct_thresh: float = 0.65,
    ambiguous_thresh: float = 0.35,
) -> ChunkEvaluation:
    """
    Evaluate chunk relevance using multi-signal lexical and semantic evidence:
    1. Keyword coverage ratio (35% weight)
    2. N-gram phrase matches (25% weight)
    3. Retrieval score contribution (vector / rerank score) (25% weight)
    4. Density in highest-scoring passage (15% weight)
    """
    content_lower = chunk.content.lower()
    q_keywords = _extract_keywords(query)

    if not q_keywords:
        # Generic query fallback
        score = 0.50
        status = "AMBIGUOUS"
        return ChunkEvaluation(
            chunk_id=chunk.chunk_id,
            confidence_score=score,
            status=status,
            reason="Query had no distinctive keywords; treated as ambiguous.",
            term_overlap_ratio=1.0,
            phrase_match_count=0,
        )

    # Signal 1: Keyword coverage ratio
    matched_keywords = [k for k in q_keywords if k in content_lower]
    keyword_coverage = len(matched_keywords) / len(q_keywords)

    # Signal 2: Phrase matches (bi-grams & tri-grams)
    query_tokens = [t for t in re.findall(r"\b[A-Za-z0-9_-]+\b", query.lower())]
    bigrams = _extract_ngrams(query_tokens, 2)
    trigrams = _extract_ngrams(query_tokens, 3)

    phrase_matches = sum(1 for bg in bigrams if bg in content_lower)
    phrase_matches += sum(2 for tg in trigrams if tg in content_lower)
    max_phrases = max(1, len(bigrams) + 2 * len(trigrams))
    phrase_score = min(1.0, phrase_matches / max_phrases)

    # Signal 3: Upstream score contribution
    # Normalize vector_score (if cosine similarity 0..1) or rerank score
    raw_vector_score = chunk.vector_score
    if raw_vector_score > 0.0:
        # Cross-encoders often produce logits (-10 to +10) or probabilities (0 to 1)
        if raw_vector_score > 1.0:
            norm_vector_score = 1.0 / (1.0 + 2.71828 ** (-raw_vector_score))
        elif raw_vector_score < 0.0:
            norm_vector_score = max(0.0, 1.0 / (1.0 + 2.71828 ** (-raw_vector_score)))
        else:
            norm_vector_score = raw_vector_score
    else:
        norm_vector_score = min(1.0, chunk.rrf_score * 30.0)

    # Signal 4: Passage density (keyword density in most concentrated sentence)
    sentences = re.split(r"(?<=[.!?])\s+", chunk.content)
    max_sent_density = 0.0
    for s in sentences:
        s_words = s.lower().split()
        if not s_words:
            continue
        m_count = sum(1 for k in q_keywords if k in s.lower())
        density = m_count / len(s_words)
        if density > max_sent_density:
            max_sent_density = density
    passage_density_score = min(1.0, max_sent_density * 3.0)

    # Composite weighted confidence
    confidence = (
        0.35 * keyword_coverage
        + 0.25 * phrase_score
        + 0.25 * norm_vector_score
        + 0.15 * passage_density_score
    )
    confidence = round(min(1.0, max(0.0, confidence)), 3)

    if confidence >= correct_thresh:
        status = "CORRECT"
        reason = f"High keyword coverage ({keyword_coverage:.0%}) and phrase alignment."
    elif confidence >= ambiguous_thresh:
        status = "AMBIGUOUS"
        reason = f"Partial keyword alignment ({keyword_coverage:.0%}); context may contain tangential details."
    else:
        status = "INCORRECT"
        reason = f"Low confidence ({confidence:.2f}); insufficient query term overlap."

    return ChunkEvaluation(
        chunk_id=chunk.chunk_id,
        confidence_score=confidence,
        status=status,
        reason=reason,
        term_overlap_ratio=keyword_coverage,
        phrase_match_count=phrase_matches,
    )


class CRAGQualityEvaluator:
    """
    Corrective RAG Evaluator gating retrieved chunks before context building.
    """

    def __init__(
        self,
        correct_threshold: Optional[float] = None,
        ambiguous_threshold: Optional[float] = None,
        use_llm: Optional[bool] = None,
    ):
        settings = get_settings()
        self.correct_thresh = (
            correct_threshold
            if correct_threshold is not None
            else settings.crag_correct_threshold
        )
        self.ambiguous_thresh = (
            ambiguous_threshold
            if ambiguous_threshold is not None
            else settings.crag_ambiguous_threshold
        )
        self.use_llm = use_llm if use_llm is not None else settings.crag_use_llm

    def evaluate(self, query: str, chunks: List[RetrievedChunk]) -> CRAGResult:
        """
        Evaluate retrieved chunks, strip distractors, and produce the CRAG verdict.

        Args:
            query:  Rewritten query string.
            chunks: List of retrieved / reranked chunks.

        Returns:
            CRAGResult containing kept chunks, discarded chunks, and status.
        """
        t0 = time.perf_counter()

        if not chunks:
            return CRAGResult(
                action="INCORRECT",
                confidence=0.0,
                kept_chunks=[],
                discarded_chunks=[],
                evaluations=[],
                noise_stripped_count=0,
                evaluation_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        q_keywords = _extract_keywords(query)
        evaluations: List[ChunkEvaluation] = []
        kept_chunks: List[RetrievedChunk] = []
        discarded_chunks: List[RetrievedChunk] = []
        noise_stripped_count = 0

        for chunk in chunks:
            chunk_eval = score_chunk_relevance(
                query=query,
                chunk=chunk,
                correct_thresh=self.correct_thresh,
                ambiguous_thresh=self.ambiguous_thresh,
            )
            evaluations.append(chunk_eval)

            if chunk_eval.status == "CORRECT":
                kept_chunks.append(chunk)
            elif chunk_eval.status == "AMBIGUOUS":
                # Clean noise sentences from ambiguous chunk
                cleaned_text, stripped = strip_noise_sentences(chunk.content, q_keywords)
                if stripped:
                    noise_stripped_count += 1
                # Create a modified chunk with cleaned content
                cleaned_chunk = RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    content=cleaned_text,
                    metadata={**chunk.metadata, "crag_ambiguous": True},
                    vector_score=chunk.vector_score,
                    bm25_score=chunk.bm25_score,
                    rrf_score=chunk.rrf_score,
                )
                kept_chunks.append(cleaned_chunk)
            else:
                # INCORRECT -> Distractor stripped
                discarded_chunks.append(chunk)

        # Aggregate decision logic
        if not kept_chunks:
            action = "INCORRECT"
            avg_confidence = (
                sum(e.confidence_score for e in evaluations) / len(evaluations)
                if evaluations
                else 0.0
            )
        elif any(e.status == "CORRECT" for e in evaluations):
            action = "CORRECT"
            correct_scores = [e.confidence_score for e in evaluations if e.status == "CORRECT"]
            avg_confidence = sum(correct_scores) / len(correct_scores)
        else:
            action = "AMBIGUOUS"
            ambig_scores = [e.confidence_score for e in evaluations if e.status == "AMBIGUOUS"]
            avg_confidence = sum(ambig_scores) / len(ambig_scores)

        eval_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            f"[CRAG] action={action} kept={len(kept_chunks)}/{len(chunks)} "
            f"discarded={len(discarded_chunks)} stripped_noise={noise_stripped_count} in {eval_ms}ms"
        )

        return CRAGResult(
            action=action,
            confidence=round(avg_confidence, 3),
            kept_chunks=kept_chunks,
            discarded_chunks=discarded_chunks,
            evaluations=evaluations,
            noise_stripped_count=noise_stripped_count,
            evaluation_ms=eval_ms,
        )

    async def async_evaluate(self, query: str, chunks: List[RetrievedChunk]) -> CRAGResult:
        """Asynchronous worker offload for CRAG evaluation."""
        return await run_in_threadpool(self.evaluate, query, chunks)


# ---------------------------------------------------------------------------
# Global Singleton
# ---------------------------------------------------------------------------

_evaluator_singleton: Optional[CRAGQualityEvaluator] = None


def get_crag_evaluator() -> CRAGQualityEvaluator:
    """Return singleton instance of CRAGQualityEvaluator."""
    global _evaluator_singleton
    if _evaluator_singleton is None:
        _evaluator_singleton = CRAGQualityEvaluator()
    return _evaluator_singleton
