"""
Reranker Agent.

Uses a cross-encoder model (ms-marco-MiniLM) to score each retrieved
chunk against the query and select the top-k most relevant ones.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from loguru import logger
from sentence_transformers import CrossEncoder

from backend.agents.retriever import RetrievedChunk
from backend.config import get_settings


@lru_cache(maxsize=1)
def _get_cross_encoder() -> CrossEncoder:
    settings = get_settings()
    logger.info(f"Loading cross-encoder: {settings.reranker_model}")
    return CrossEncoder(settings.reranker_model)


def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    top_k: Optional[int] = None,
) -> list[RetrievedChunk]:
    """
    Score and rerank retrieved chunks with a cross-encoder.

    Args:
        query:  The (rewritten) query string.
        chunks: Candidates from the hybrid retriever.
        top_k:  How many top chunks to return (defaults to settings.top_k_rerank).

    Returns:
        Top-k chunks sorted by cross-encoder score descending.
    """
    if not chunks:
        return []

    settings = get_settings()
    if top_k is None:
        top_k = settings.top_k_rerank

    cross_encoder = _get_cross_encoder()
    pairs = [(query, chunk.content) for chunk in chunks]

    try:
        scores: list[float] = cross_encoder.predict(pairs).tolist()
    except Exception as exc:
        logger.warning(f"[Reranker] Cross-encoder failed ({exc}), falling back to RRF order.")
        return chunks[:top_k]

    for chunk, score in zip(chunks, scores):
        chunk.vector_score = float(score)  # repurpose vector_score field for cross-enc score

    ranked = sorted(chunks, key=lambda c: c.vector_score, reverse=True)[:top_k]

    logger.info(
        f"[Reranker] {len(chunks)} → {len(ranked)} chunks. "
        f"Top score: {ranked[0].vector_score:.4f}"
    )
    return ranked
