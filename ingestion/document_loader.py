"""
Re-export document loader from backend.ingestion.document_loader for root-level imports.
"""

from backend.ingestion.document_loader import (
    RawDocument,
    format_table_as_markdown,
    load_document,
)

__all__ = ["RawDocument", "format_table_as_markdown", "load_document"]
