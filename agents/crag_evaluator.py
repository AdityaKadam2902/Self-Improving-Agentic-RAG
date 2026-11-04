"""
Re-export CRAG evaluator from backend.agents.crag_evaluator for root-level imports.
"""

from backend.agents.crag_evaluator import (
    ChunkEvaluation,
    CRAGResult,
    CRAGQualityEvaluator,
    get_crag_evaluator,
    score_chunk_relevance,
    strip_noise_sentences,
)

__all__ = [
    "ChunkEvaluation",
    "CRAGResult",
    "CRAGQualityEvaluator",
    "get_crag_evaluator",
    "score_chunk_relevance",
    "strip_noise_sentences",
]
