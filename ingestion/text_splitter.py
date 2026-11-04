"""
Re-export text splitter from backend.ingestion.text_splitter for root-level imports.
"""

from backend.ingestion.text_splitter import (
    TextChunk,
    RecursiveTextSplitterFallback,
    synthesize_document_summary,
    split_documents,
)

__all__ = [
    "TextChunk",
    "RecursiveTextSplitterFallback",
    "synthesize_document_summary",
    "split_documents",
]
