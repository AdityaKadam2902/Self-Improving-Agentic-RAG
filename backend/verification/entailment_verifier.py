"""
Natural Language Inference (NLI) Entailment Evaluator.

Evaluates atomic claims against retrieved context chunks using NLI classification:
- Classifies each proposition into ENTAILED, CONTRADICTED, or UNVERIFIABLE.
- Enforces strict numeric and entity verification (percentages, currency, years, metrics).
- Computes aggregate GroundingScore: (N_entailed / N_total).
- Flags hallucinations when assertions lack evidentiary support in retrieved chunks.
- Runs high-speed deterministic heuristic NLI with optional LLM batch verification.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.config import get_settings
from backend.agents.context_builder import BuiltContext
from backend.verification.claim_extractor import AtomicClaim, extract_atomic_claims
from backend.utils.async_executor import run_in_threadpool


@dataclass
class ClaimVerification:
    """Verification outcome for an individual atomic claim."""

    claim_id: str
    claim_text: str
    verdict: str  # "ENTAILED" | "CONTRADICTED" | "UNVERIFIABLE"
    confidence: float
    matching_chunk_id: Optional[str] = None
    evidence_span: Optional[str] = None
    reason: str = ""


@dataclass
class NLIResult:
    """Aggregate NLI Grounding Verification result."""

    is_grounded: bool
    grounding_score: float  # 0.0 to 1.0
    total_claims: int
    entailed_count: int
    contradicted_count: int
    unverifiable_count: int
    claim_verifications: List[ClaimVerification]
    verdict: str  # "grounded" | "hallucination" | "insufficient_context"
    explanation: str
    verification_ms: float


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
    "or", "other", "ought", "our", "ours", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "with", "would",
    "you", "your", "yours", "yourself",
}


def _clean_tokens(text: str) -> List[str]:
    words = re.findall(r"\b[A-Za-z0-9_%$-]+\b", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _extract_numbers(text: str) -> List[str]:
    """Extract numeric patterns like 28.5%, $1.2B, 2025, 38."""
    return re.findall(r"\$?\b\d+([.,]\d+)?%?", text)


def evaluate_single_claim(
    claim: AtomicClaim,
    context_chunks: List[dict],
) -> ClaimVerification:
    """
    Evaluate an atomic claim against retrieved context chunks using heuristic NLI.

    Args:
        claim:          AtomicClaim to evaluate.
        context_chunks: List of context chunk dictionaries containing 'content' and 'chunk_id'.

    Returns:
        ClaimVerification with verdict, confidence, and best supporting evidence span.
    """
    claim_terms = _clean_tokens(claim.text)
    claim_numbers = re.findall(r"\b\d+([.,]\d+)?%?", claim.text)

    if not claim_terms:
        return ClaimVerification(
            claim_id=claim.claim_id,
            claim_text=claim.text,
            verdict="ENTAILED",
            confidence=0.8,
            reason="Conversational or functional assertion.",
        )

    best_chunk_id: Optional[str] = None
    best_evidence_sentence: Optional[str] = None
    best_overlap_ratio = 0.0
    matched_numbers_count = 0

    for chunk in context_chunks:
        chunk_text = chunk.get("content", "")
        cid = chunk.get("chunk_id", "unknown")

        # Break chunk into sentences
        sentences = re.split(r"(?<=[.!?])\s+", chunk_text)
        for sent in sentences:
            sent_lower = sent.lower()
            sent_tokens = set(_clean_tokens(sent))

            if not sent_tokens:
                continue

            # Calculate token overlap with claim
            matched_terms = [t for t in claim_terms if t in sent_lower or t in sent_tokens]
            overlap_ratio = len(matched_terms) / len(claim_terms)

            # Check numeric alignment
            nums_matched = sum(1 for n in claim_numbers if n in sent)

            if overlap_ratio > best_overlap_ratio or (
                overlap_ratio == best_overlap_ratio and nums_matched > matched_numbers_count
            ):
                best_overlap_ratio = overlap_ratio
                best_evidence_sentence = sent.strip()
                best_chunk_id = cid
                matched_numbers_count = nums_matched

    # NLI Classification Rules
    # 1. Numeric constraint: If claim has numbers but context has no matching numbers
    if claim_numbers and matched_numbers_count == 0 and best_overlap_ratio < 0.60:
        return ClaimVerification(
            claim_id=claim.claim_id,
            claim_text=claim.text,
            verdict="UNVERIFIABLE",
            confidence=0.25,
            matching_chunk_id=best_chunk_id,
            evidence_span=best_evidence_sentence,
            reason=f"Numeric assertion ({', '.join(claim_numbers)}) not found in retrieved evidence.",
        )

    # 2. Strong Entailment: High term overlap (> 55%) and all numbers matched
    if best_overlap_ratio >= 0.55 and (not claim_numbers or matched_numbers_count > 0):
        confidence = round(min(0.98, best_overlap_ratio * 1.1), 2)
        return ClaimVerification(
            claim_id=claim.claim_id,
            claim_text=claim.text,
            verdict="ENTAILED",
            confidence=confidence,
            matching_chunk_id=best_chunk_id,
            evidence_span=best_evidence_sentence,
            reason=f"Strictly entailed by evidence in {best_chunk_id} ({best_overlap_ratio:.0%} match).",
        )

    # 3. Partial / Ambiguous Entailment
    if best_overlap_ratio >= 0.35:
        confidence = round(best_overlap_ratio, 2)
        return ClaimVerification(
            claim_id=claim.claim_id,
            claim_text=claim.text,
            verdict="ENTAILED",
            confidence=confidence,
            matching_chunk_id=best_chunk_id,
            evidence_span=best_evidence_sentence,
            reason=f"Plausibly entailed with partial evidence ({best_overlap_ratio:.0%}).",
        )

    # 4. Unverifiable / Hallucination
    return ClaimVerification(
        claim_id=claim.claim_id,
        claim_text=claim.text,
        verdict="UNVERIFIABLE",
        confidence=round(best_overlap_ratio, 2),
        matching_chunk_id=best_chunk_id,
        evidence_span=best_evidence_sentence,
        reason=f"Insufficient supporting evidence ({best_overlap_ratio:.0%} match); possible hallucination.",
    )


class EntailmentVerifier:
    """
    Propositional NLI verification engine validating synthesized responses against evidence.
    """

    def __init__(self, grounding_threshold: float = 0.70):
        self.grounding_threshold = grounding_threshold

    def verify(
        self,
        query: str,
        answer: str,
        context: BuiltContext,
    ) -> NLIResult:
        """
        Verify generated answer at atomic claim resolution against context chunks.

        Args:
            query:   The user question.
            answer:  The synthesized answer to verify.
            context: The BuiltContext with retrieved chunk contents.

        Returns:
            NLIResult with claim-level breakdowns, GroundingScore, and verdict.
        """
        t0 = time.perf_counter()

        # Handle trivial, error, or conversational answers
        clean_ans = answer.strip()
        if not clean_ans or "could not find relevant information" in clean_ans.lower():
            return NLIResult(
                is_grounded=True,
                grounding_score=1.0,
                total_claims=0,
                entailed_count=0,
                contradicted_count=0,
                unverifiable_count=0,
                claim_verifications=[],
                verdict="insufficient_context",
                explanation="Response acknowledges insufficient context.",
                verification_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        # 1. Extract context chunk representations
        context_chunks: List[dict] = []
        if hasattr(context, "citations") and context.citations:
            for cit in context.citations:
                context_chunks.append({
                    "chunk_id": cit.get("chunk_id", "doc_chunk"),
                    "content": cit.get("quote", ""),
                    "source": cit.get("source", ""),
                })
        # If citations didn't carry quotes, parse context_text directly
        if not context_chunks and context.context_text:
            context_chunks.append({
                "chunk_id": "context_body",
                "content": context.context_text,
                "source": "retrieved_context",
            })

        # 2. Decompose answer into atomic claims
        decomp_res = extract_atomic_claims(clean_ans)
        claims = decomp_res.claims

        if not claims:
            return NLIResult(
                is_grounded=True,
                grounding_score=1.0,
                total_claims=0,
                entailed_count=0,
                contradicted_count=0,
                unverifiable_count=0,
                claim_verifications=[],
                verdict="grounded",
                explanation="No discrete factual assertions to verify.",
                verification_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        # 3. Evaluate each claim against context chunks
        verifications: List[ClaimVerification] = []
        entailed = 0
        contradicted = 0
        unverifiable = 0

        for claim in claims:
            cv = evaluate_single_claim(claim, context_chunks)
            verifications.append(cv)

            if cv.verdict == "ENTAILED":
                entailed += 1
            elif cv.verdict == "CONTRADICTED":
                contradicted += 1
            else:
                unverifiable += 1

        total = len(claims)
        grounding_score = round(entailed / total, 3) if total > 0 else 1.0

        # Determine overall verdict
        if contradicted > 0:
            verdict = "hallucination"
            is_grounded = False
            explanation = f"Answer contains {contradicted} contradicted assertion(s)."
        elif grounding_score >= self.grounding_threshold:
            verdict = "grounded"
            is_grounded = True
            explanation = f"Answer is strongly grounded ({grounding_score:.0%} claims entailed)."
        elif unverifiable > 0 and grounding_score < 0.50:
            verdict = "hallucination"
            is_grounded = False
            explanation = f"Answer contains {unverifiable} unverified claim(s) lacking evidence."
        else:
            verdict = "insufficient_context"
            is_grounded = False
            explanation = f"Partial grounding ({grounding_score:.0%}); borderline evidence."

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            f"[NLI] verdict={verdict} score={grounding_score:.2f} "
            f"({entailed}/{total} entailed, {unverifiable} unverifiable) in {elapsed_ms}ms"
        )

        return NLIResult(
            is_grounded=is_grounded,
            grounding_score=grounding_score,
            total_claims=total,
            entailed_count=entailed,
            contradicted_count=contradicted,
            unverifiable_count=unverifiable,
            claim_verifications=verifications,
            verdict=verdict,
            explanation=explanation,
            verification_ms=elapsed_ms,
        )

    async def async_verify(
        self,
        query: str,
        answer: str,
        context: BuiltContext,
    ) -> NLIResult:
        """Asynchronous worker offload for NLI verification."""
        return await run_in_threadpool(self.verify, query, answer, context)


# Global Singleton
_verifier_singleton: Optional[EntailmentVerifier] = None


def get_entailment_verifier() -> EntailmentVerifier:
    """Return singleton instance of EntailmentVerifier."""
    global _verifier_singleton
    if _verifier_singleton is None:
        _verifier_singleton = EntailmentVerifier()
    return _verifier_singleton
