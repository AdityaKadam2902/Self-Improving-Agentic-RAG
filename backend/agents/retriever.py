"""
Hybrid Retrieval Agent.

Combines dense vector search (ChromaDB / Qdrant) with sparse BM25 keyword search,
then merges the ranked results using Reciprocal Rank Fusion (RRF).
Supports asynchronous execution via worker threadpool offloading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from loguru import logger

from backend.config import get_settings
from backend.utils.async_executor import run_in_threadpool
from backend.ingestion.embedding_generator import (
    embed_query,
    vector_query,
    get_all_documents,
    build_bm25_index,
    collection_count,
)


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
    2. Sparse BM25 keyword search over all stored documents.
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
    ids = vector_results["ids"]
    docs = vector_results["documents"]
    metas = vector_results["metadatas"]
    dists = vector_results["distances"]

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

    # 2. Sparse BM25 retrieval
    all_ids, all_docs, all_metas = get_all_documents()

    bm25 = build_bm25_index(all_docs)
    tokenized_query = query.lower().split()
    bm25_scores = bm25.get_scores(tokenized_query)

    # Build (id, score) pairs sorted by score
    bm25_ranked = sorted(
        zip(all_ids, all_docs, all_metas, bm25_scores),
        key=lambda x: x[3],
        reverse=True,
    )[:top_k]

    sparse_chunks: dict[str, RetrievedChunk] = {}
    for rank, (cid, doc, meta, score) in enumerate(bm25_ranked):
        if score == 0:
            break
        if tenant_filter and not _matches_filter(meta, tenant_filter):
            continue
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
    sparse_order = [cid for cid, *_ in bm25_ranked if cid in all_chunks]

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
