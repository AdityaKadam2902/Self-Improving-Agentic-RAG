"""
Text chunking pipeline.

Splits RawDocument pages into smaller, overlapping chunks using
LangChain's RecursiveCharacterTextSplitter with tiktoken token counting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from backend.ingestion.document_loader import RawDocument


@dataclass
class TextChunk:
    """A single text chunk ready for embedding."""

    chunk_id: str
    content: str
    metadata: dict = field(default_factory=dict)


def split_documents(
    raw_docs: list[RawDocument],
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> list[TextChunk]:
    """
    Split raw documents into overlapping chunks.

    Args:
        raw_docs:      Pages / sections from the document loader.
        chunk_size:    Maximum tokens per chunk.
        chunk_overlap: Overlap tokens between adjacent chunks.

    Returns:
        Flat list of TextChunk objects.
    """
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-3.5-turbo",  # tiktoken encoding – no API call made
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[TextChunk] = []

    for doc in raw_docs:
        pieces = splitter.split_text(doc.content)
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 0)

        for idx, piece in enumerate(pieces):
            chunk_id = f"{source}_p{page}_c{idx}"
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    content=piece,
                    metadata={
                        **doc.metadata,
                        "chunk_index": idx,
                        "chunk_id": chunk_id,
                    },
                )
            )

    logger.info(
        f"Split {len(raw_docs)} pages → {len(chunks)} chunks "
        f"(size={chunk_size}, overlap={chunk_overlap})"
    )
    return chunks
