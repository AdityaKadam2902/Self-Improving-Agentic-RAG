"""
Ingestion package exports.
"""

from backend.ingestion.document_loader import (
    RawDocument,
    format_table_as_markdown,
    load_document,
)
from backend.ingestion.text_splitter import (
    TextChunk,
    RecursiveTextSplitterFallback,
    synthesize_document_summary,
    split_documents,
)
from backend.ingestion.cached_bm25 import (
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
