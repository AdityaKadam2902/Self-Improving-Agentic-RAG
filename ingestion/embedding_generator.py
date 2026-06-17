"""
Embedding generation and vector store management.

Supports two backends, selected via the VECTOR_BACKEND env var:
  - "chroma"  (default) — ChromaDB with persistent HNSW index
  - "qdrant"            — Qdrant in-memory (pure Python, no C++ deps)

Use VECTOR_BACKEND=qdrant if chromadb cannot be installed on your
platform (common on Python 3.14 before binary wheels are released).

Handles:
  - Generating embeddings with sentence-transformers
  - Upserting chunks into the chosen vector store
  - Keyword index (BM25) construction for hybrid retrieval
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Any

from loguru import logger
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from backend.config import get_settings
from backend.ingestion.text_splitter import TextChunk


# ── Embedding model singleton ─────────────────────────────────────────────────

_embedding_model: Optional[SentenceTransformer] = None


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        settings = get_settings()
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _embedding_model = SentenceTransformer(settings.embedding_model)
    return _embedding_model


# ── Backend selection ─────────────────────────────────────────────────────────

_BACKEND = os.environ.get("VECTOR_BACKEND", "chroma").lower()


# ══════════════════════════════════════════════════════════════════════════════
#  ChromaDB backend
# ══════════════════════════════════════════════════════════════════════════════

_chroma_client: Any = None


def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        settings = get_settings()
        Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def _get_chroma_collection():
    client = _get_chroma_client()
    settings = get_settings()
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Qdrant in-memory backend  (pure Python — no C++ build required)
# ══════════════════════════════════════════════════════════════════════════════

_qdrant_client: Any = None
_qdrant_store: dict = {"ids": [], "documents": [], "embeddings": [], "metadatas": []}


def _get_qdrant_client():
    """Lazy-init Qdrant in-memory client."""
    global _qdrant_client
    if _qdrant_client is None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            settings = get_settings()
            model = _get_embedding_model()
            dim = model.get_sentence_embedding_dimension()

            _qdrant_client = QdrantClient(":memory:")
            _qdrant_client.recreate_collection(
                collection_name=settings.chroma_collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            logger.info(f"Qdrant in-memory client initialised (dim={dim})")
        except ImportError:
            raise ImportError(
                "VECTOR_BACKEND=qdrant but qdrant-client is not installed.\n"
                "Run: pip install qdrant-client"
            )
    return _qdrant_client


# ══════════════════════════════════════════════════════════════════════════════
#  Unified public interface
# ══════════════════════════════════════════════════════════════════════════════

def get_collection():
    """
    Return the active vector store collection handle.
    Returns a ChromaDB Collection or the Qdrant client depending on backend.
    """
    if _BACKEND == "qdrant":
        return _get_qdrant_client()
    return _get_chroma_collection()


def embed_and_store(chunks: list[TextChunk]) -> None:
    """
    Generate embeddings for *chunks* and upsert them into the vector store.

    Args:
        chunks: TextChunk objects from the text splitter.
    """
    if not chunks:
        logger.warning("embed_and_store called with empty chunk list – skipping.")
        return

    model = _get_embedding_model()
    texts = [c.content for c in chunks]
    ids = [c.chunk_id for c in chunks]
    metadatas = [c.metadata for c in chunks]

    logger.info(f"Generating embeddings for {len(chunks)} chunks …")
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32).tolist()

    if _BACKEND == "qdrant":
        _qdrant_upsert(ids, texts, embeddings, metadatas)
    else:
        _chroma_upsert(ids, texts, embeddings, metadatas)

    logger.success(f"Stored {len(chunks)} chunks via {_BACKEND} backend.")


def _chroma_upsert(ids, texts, embeddings, metadatas):
    collection = _get_chroma_collection()
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            documents=texts[i:i + batch_size],
            embeddings=embeddings[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )


def _qdrant_upsert(ids, texts, embeddings, metadatas):
    from qdrant_client.models import PointStruct

    settings = get_settings()
    client = _get_qdrant_client()
    points = [
        PointStruct(
            id=abs(hash(cid)) % (2 ** 31),
            vector=emb,
            payload={"chunk_id": cid, "document": txt, **meta},
        )
        for cid, txt, emb, meta in zip(ids, texts, embeddings, metadatas)
    ]
    client.upsert(collection_name=settings.chroma_collection, points=points)

    # Also keep a flat store for BM25 access
    _qdrant_store["ids"].extend(ids)
    _qdrant_store["documents"].extend(texts)
    _qdrant_store["embeddings"].extend(embeddings)
    _qdrant_store["metadatas"].extend(metadatas)


def embed_query(query: str) -> list[float]:
    """Return embedding vector for a single query string."""
    model = _get_embedding_model()
    return model.encode([query], show_progress_bar=False)[0].tolist()


def get_all_documents() -> tuple[list[str], list[str], list[dict]]:
    """
    Return (ids, documents, metadatas) for all stored chunks.
    Used by the hybrid retriever and BM25 indexer.
    """
    if _BACKEND == "qdrant":
        return (
            _qdrant_store["ids"],
            _qdrant_store["documents"],
            _qdrant_store["metadatas"],
        )

    collection = _get_chroma_collection()
    result = collection.get(include=["documents", "metadatas"])
    return (
        result.get("ids") or [],
        result.get("documents") or [],
        result.get("metadatas") or [],
    )


def vector_query(query_embedding: list[float], top_k: int) -> dict:
    """
    Perform a nearest-neighbour search and return a ChromaDB-style result dict.
    """
    if _BACKEND == "qdrant":
        return _qdrant_query(query_embedding, top_k)

    collection = _get_chroma_collection()
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    return {
        "ids": raw["ids"][0],
        "documents": raw["documents"][0],
        "metadatas": raw["metadatas"][0],
        "distances": raw["distances"][0],
    }


def _qdrant_query(query_embedding: list[float], top_k: int) -> dict:
    settings = get_settings()
    client = _get_qdrant_client()
    hits = client.search(
        collection_name=settings.chroma_collection,
        query_vector=query_embedding,
        limit=top_k,
    )
    ids, docs, metas, dists = [], [], [], []
    for hit in hits:
        payload = hit.payload or {}
        ids.append(payload.get("chunk_id", str(hit.id)))
        docs.append(payload.get("document", ""))
        meta = {k: v for k, v in payload.items() if k not in ("chunk_id", "document")}
        metas.append(meta)
        dists.append(1.0 - hit.score)  # cosine distance
    return {"ids": ids, "documents": docs, "metadatas": metas, "distances": dists}


def collection_count() -> int:
    """Return total number of stored chunks."""
    if _BACKEND == "qdrant":
        return len(_qdrant_store["ids"])
    return _get_chroma_collection().count()


def build_bm25_index(documents: Optional[list[str]] = None) -> BM25Okapi:
    """
    Build a BM25 index from *documents* or from all stored docs.

    Args:
        documents: Optional pre-fetched list of document texts.

    Returns:
        Fitted BM25Okapi instance.
    """
    if documents is None:
        _, documents, _ = get_all_documents()

    tokenized = [doc.lower().split() for doc in (documents or [])]
    return BM25Okapi(tokenized if tokenized else [[]])
