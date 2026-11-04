"""
Hybrid Retrieval Agent with Persistent Incremental BM25 Inverted Index.

Combines dense vector search (ChromaDB / Qdrant) with high-speed sparse BM25 inverted
index lookup (<5 ms), then merges the ranked results using Reciprocal Rank Fusion (RRF).
Supports asynchronous execution via worker threadpool offloading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.config import get_settings
from backend.utils.async_executor import run_in_threadpool
from backend.ingestion.embedding_generator import (
    embed_query,
    vector_query,
    get_all_documents,
    collection_count,
)
from backend.ingestion.cached_bm25 import get_bm25_index


@dataclass
class RetrievedChunk:
    """A single chunk retrieved by the hybrid retriever."""

    chunk_id: str
    content: str
    metadata: dict = field(default_factory=dict)
    vector_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0


def hybrid_retrieve(
    query: str,
    top_k: int | None = None,
    tenant_filter: Optional[Dict[str, Any]] = None,
) -> list[RetrievedChunk]:
    """
    Perform synchronous hybrid retrieval for *query*.

    1. Dense vector search via ChromaDB/Qdrant cosine similarity.
    2. High-speed sparse BM25 inverted index lookup (<5 ms).
    3. Reciprocal Rank Fusion to merge rankings.

    Args:
        query: The (rewritten) query string.
        top_k: Number of results to return (defaults to settings.top_k_retrieval).
        tenant_filter: Optional metadata filter for multi-tenant isolation.

    Returns:
        List of RetrievedChunk objects sorted by RRF score descending.
    """
    settings = get_settings()
    if top_k is None:
        top_k = settings.top_k_retrieval

    total_docs = collection_count()

    if total_docs == 0:
        logger.warning("[Retriever] Collection is empty - returning no results.")
        return []

    # 1. Dense retrieval
    query_embedding = embed_query(query)
    vector_results = vector_query(query_embedding, top_k=min(top_k, total_docs))

    dense_chunks: dict[str, RetrievedChunk] = {}
    ids = vector_results.get("ids", [])
    docs = vector_results.get("documents", [])
    metas = vector_results.get("metadatas", [])
    dists = vector_results.get("distances", [])

    for rank, (cid, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists)):
        # Apply tenant filter if provided
        if tenant_filter and not _matches_filter(meta, tenant_filter):
            continue
        dense_chunks[cid] = RetrievedChunk(
            chunk_id=cid,
            content=doc,
            metadata=meta or {},
            vector_score=1.0 - dist,  # cosine distance -> similarity
        )

    # 2. Sparse BM25 retrieval using Persistent Inverted Index
    bm25_idx = get_bm25_index()
    # If the in-memory BM25 index is empty but vector collection has docs, seed it
    if bm25_idx.total_docs == 0 and total_docs > 0:
        try:
            all_ids, all_docs, all_metas = get_all_documents()
            seed_tuples = list(zip(all_ids, all_docs, all_metas))
            bm25_idx.add_documents(seed_tuples, persist=True)
        except Exception as e:
            logger.warning(f"[Retriever] Failed to seed BM25 index: {e}")

    bm25_results = bm25_idx.query(query, top_k=top_k, tenant_filter=tenant_filter)

    sparse_chunks: dict[str, RetrievedChunk] = {}
    for cid, doc, meta, score in bm25_results:
        if cid in dense_chunks:
            dense_chunks[cid].bm25_score = score
        else:
            sparse_chunks[cid] = RetrievedChunk(
                chunk_id=cid,
                content=doc,
                metadata=meta or {},
                bm25_score=score,
            )

    # 3. Reciprocal Rank Fusion
    all_chunks: dict[str, RetrievedChunk] = {**dense_chunks, **sparse_chunks}
    dense_order = list(dense_chunks.keys())
    sparse_order = [cid for cid, _, _, _ in bm25_results if cid in all_chunks]

    k_rrf = 60  # standard RRF constant
    for cid, chunk in all_chunks.items():
        dense_rank = dense_order.index(cid) + 1 if cid in dense_order else len(dense_order) + 1
        sparse_rank = sparse_order.index(cid) + 1 if cid in sparse_order else len(sparse_order) + 1
        chunk.rrf_score = 1.0 / (k_rrf + dense_rank) + 1.0 / (k_rrf + sparse_rank)

    results = sorted(all_chunks.values(), key=lambda c: c.rrf_score, reverse=True)[:top_k]
    logger.info(f"[Retriever] query='{query[:60]}' -> {len(results)} chunks (hybrid RRF)")
    return results


async def async_hybrid_retrieve(
    query: str,
    top_k: int | None = None,
    tenant_filter: Optional[Dict[str, Any]] = None,
) -> list[RetrievedChunk]:
    """
    Asynchronous non-blocking wrapper for hybrid retrieval.
    Offloads dense embedding and BM25 computations to the worker threadpool.
    """
    return await run_in_threadpool(hybrid_retrieve, query, top_k, tenant_filter)


def _matches_filter(meta: dict, tenant_filter: dict) -> bool:
    """Helper to check if chunk metadata satisfies access criteria."""
    for key, expected_value in tenant_filter.items():
        if isinstance(expected_value, list):
            if meta.get(key) not in expected_value:
                return False
        elif meta.get(key) != expected_value:
            return False
    return True
