"""
Context Builder Agent.

Takes the top-k reranked chunks and formats them into a structured
context block that is safe and informative for the answer generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.agents.retriever import RetrievedChunk


@dataclass
class BuiltContext:
    """Structured context ready for the Answer Generator."""

    context_text: str          # Formatted text to inject into the LLM prompt
    citations: list[dict]      # [{"source": ..., "page": ..., "chunk_id": ...}]
    chunk_ids: list[str]       # Raw chunk IDs for verification


def build_context(chunks: list[RetrievedChunk]) -> BuiltContext:
    """
    Format reranked chunks into a labelled context block with citations.

    Args:
        chunks: Reranked RetrievedChunk objects (usually top 3).

    Returns:
        BuiltContext with formatted text and citation metadata.
    """
    if not chunks:
        return BuiltContext(
            context_text="[No relevant context found in the uploaded documents.]",
            citations=[],
            chunk_ids=[],
        )

    parts: list[str] = []
    citations: list[dict] = []

    for idx, chunk in enumerate(chunks, start=1):
        source = chunk.metadata.get("source", "unknown")
        page = chunk.metadata.get("page", "?")
        chunk_id = chunk.chunk_id

        label = f"[Source {idx}: {source}, page {page}]"
        parts.append(f"{label}\n{chunk.content.strip()}")

        citations.append(
            {
                "reference": f"Source {idx}",
                "source": source,
                "page": page,
                "chunk_id": chunk_id,
                "score": round(chunk.vector_score, 4),
            }
        )

    context_text = "\n\n".join(parts)
    logger.info(f"[ContextBuilder] Built context from {len(chunks)} chunks ({len(context_text)} chars)")

    return BuiltContext(
        context_text=context_text,
        citations=citations,
        chunk_ids=[c.chunk_id for c in chunks],
    )
