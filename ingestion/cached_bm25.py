"""
Re-export cached BM25 index from backend.ingestion.cached_bm25 for root-level imports.
"""

from backend.ingestion.cached_bm25 import (
    PersistentBM25Index,
    get_bm25_index,
)

__all__ = ["PersistentBM25Index", "get_bm25_index"]
