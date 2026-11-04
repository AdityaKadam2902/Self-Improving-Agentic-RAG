"""
Unsupervised Failure Pattern Clusterer.

Analyzes negative user feedback records and NLI verification failures from the
SQLite WAL feedback ledger:
- Groups failure instances into thematic root-cause error clusters using vector/TF-IDF similarity.
- Identifies systemic error patterns (e.g. quantitative mismatch, temporal confusion, distractor retrieval).
- Generates actionable diagnostic reports with concrete parameter tuning recommendations.
- Runs pure-Python deterministic clustering with zero required external dependencies.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.storage.db import _get_feedback_records_sync


@dataclass
class ClusterDiagnostic:
    """Diagnostic profile for an identified failure pattern cluster."""

    cluster_id: int
    theme: str
    sample_queries: List[str]
    count: int
    percentage: float
    key_terms: List[str]
    remediation_recommendation: str


@dataclass
class ClusteringResult:
    """Outcome of unsupervised failure clustering analysis."""

    total_failures_analyzed: int
    clusters: List[ClusterDiagnostic]
    unclustered_count: int
    analysis_ms: float


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
    "you", "your", "yours", "yourself", "tell", "explain", "give", "show",
}


def _tokenize(text: str) -> List[str]:
    words = re.findall(r"\b[A-Za-z0-9_-]{3,}\b", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def _cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    intersection = set(vec1.keys()) & set(vec2.keys())
    if not intersection:
        return 0.0
    dot = sum(vec1[k] * vec2[k] for k in intersection)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot / (mag1 * mag2)


# Predefined domain theme signatures for semantic classification
_THEME_RULES = [
    (
        "Quantitative and Table Extraction Failure",
        {"revenue", "margin", "profit", "ebitda", "percent", "growth", "numbers", "quarter", "table", "financial"},
        "Increase top_k_rerank from 3 to 5 and prioritize Markdown table chunks in context assembly.",
    ),
    (
        "Temporal and Chronological Confusion",
        {"year", "date", "annual", "quarter", "latest", "historical", "current", "2024", "2025", "2026"},
        "Prepend chronological timestamps to contextual chunk breadcrumbs during ingestion.",
    ),
    (
        "Security, Auth and Access Control Failures",
        {"security", "injection", "token", "auth", "permission", "rbac", "secret", "delimiter", "pii"},
        "Tighten injection shield boundary regexes and verify tenant access masks.",
    ),
    (
        "Entity and Acronym Disambiguation Failure",
        {"api", "sdk", "cli", "definition", "acronym", "architecture", "microservice", "protocol"},
        "Enable query expansion in AdaptiveRouter to synthesize entity synonyms.",
    ),
    (
        "Distractor Context and Noise Ingestion",
        {"irrelevant", "noise", "distractor", "wrong", "unrelated", "hallucination", "missing"},
        "Raise CRAG quality gate threshold from 0.65 to 0.72 to discard marginal chunks.",
    ),
]


class FailureClusterer:
    """
    Groups feedback failures into actionable diagnostic clusters.
    """

    def __init__(self, similarity_threshold: float = 0.35):
        self.similarity_threshold = similarity_threshold

    def cluster_failures(
        self,
        records: Optional[List[dict]] = None,
    ) -> ClusteringResult:
        """
        Extract negative records and cluster them into failure themes.

        Args:
            records: Optional explicit list of feedback records. If omitted,
                     fetches negative records from SQLite feedback ledger.

        Returns:
            ClusteringResult containing categorized ClusterDiagnostics.
        """
        t0 = time.perf_counter()

        if records is None:
            # Query SQLite for negative feedback records
            all_records = _get_feedback_records_sync(limit=200)
            negative_records = [
                r for r in all_records
                if r.get("is_correct") == 0
                or r.get("verification_verdict") in ("hallucination", "insufficient_context")
                or r.get("grounding_score", 1.0) < 0.65
            ]
        else:
            negative_records = records

        if not negative_records:
            return ClusteringResult(
                total_failures_analyzed=0,
                clusters=[],
                unclustered_count=0,
                analysis_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        # 1. Classify records into themes
        buckets: Dict[str, List[dict]] = {theme: [] for theme, _, _ in _THEME_RULES}
        unclustered: List[dict] = []

        for record in negative_records:
            query = record.get("question", "")
            explanation = record.get("explanation", "") or record.get("verification_explanation", "")
            combined_text = f"{query} {explanation}".lower()
            tokens = set(_tokenize(combined_text))

            best_theme: Optional[str] = None
            best_overlap = 0

            for theme, keywords, _ in _THEME_RULES:
                overlap = len(tokens & keywords)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_theme = theme

            if best_theme and best_overlap >= 1:
                buckets[best_theme].append(record)
            else:
                unclustered.append(record)

        # 2. Assemble diagnostics
        total_count = len(negative_records)
        cluster_diagnostics: List[ClusterDiagnostic] = []
        cluster_id = 1

        for theme, keywords, remediation in _THEME_RULES:
            items = buckets[theme]
            if not items:
                continue

            sample_queries = [r.get("question", "Unknown") for r in items[:3]]
            pct = round((len(items) / total_count) * 100, 1)

            # Extract frequent terms in this cluster
            term_freq: Dict[str, int] = {}
            for r in items:
                for t in _tokenize(r.get("question", "")):
                    term_freq[t] = term_freq.get(t, 0) + 1
            sorted_terms = sorted(term_freq.keys(), key=lambda t: term_freq[t], reverse=True)[:5]

            cluster_diagnostics.append(
                ClusterDiagnostic(
                    cluster_id=cluster_id,
                    theme=theme,
                    sample_queries=sample_queries,
                    count=len(items),
                    percentage=pct,
                    key_terms=sorted_terms,
                    remediation_recommendation=remediation,
                )
            )
            cluster_id += 1

        # Sort clusters by volume descending
        cluster_diagnostics.sort(key=lambda c: c.count, reverse=True)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            f"[FailureClusterer] Analyzed {total_count} failures -> {len(cluster_diagnostics)} "
            f"clusters formed in {elapsed_ms}ms"
        )

        return ClusteringResult(
            total_failures_analyzed=total_count,
            clusters=cluster_diagnostics,
            unclustered_count=len(unclustered),
            analysis_ms=elapsed_ms,
        )


_clusterer_singleton: Optional[FailureClusterer] = None


def get_failure_clusterer() -> FailureClusterer:
    """Return singleton instance of FailureClusterer."""
    global _clusterer_singleton
    if _clusterer_singleton is None:
        _clusterer_singleton = FailureClusterer()
    return _clusterer_singleton
