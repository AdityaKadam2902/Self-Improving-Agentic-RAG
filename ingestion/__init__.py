"""
Ingestion package exports for root-level access.
"""

from backend.ingestion import (
    RawDocument,
    format_table_as_markdown,
    load_document,
    TextChunk,
    RecursiveTextSplitterFallback,
    synthesize_document_summary,
    split_documents,
    PersistentBM25Index,
    get_bm25_index,
)

__all__ = [
    "RawDocument",
    "format_table_as_markdown",
    "load_document",
    "TextChunk",
    "RecursiveTextSplitterFallback",
    "synthesize_document_summary",
    "split_documents",
    "PersistentBM25Index",
    "get_bm25_index",
]
