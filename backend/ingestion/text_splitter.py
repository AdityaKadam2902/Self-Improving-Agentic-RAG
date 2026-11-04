"""
Contextual Chunk Enrichment and Text Splitting Pipeline.

Splits RawDocument pages/sections into overlapping chunks enriched with:
- Global document-level extractive contextual summary.
- Structural breadcrumbs prepended to each chunk:
    "[Document: {source} | Section: {section_title} | Context: {summary}]"
- Full metadata tracking (section hierarchy, table presence, raw vs enriched text).
- Pure-Python recursive splitter fallback when LangChain is not installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.ingestion.document_loader import RawDocument


@dataclass
class TextChunk:
    """A single text chunk enriched with contextual breadcrumbs ready for vector and BM25 indexing."""

    chunk_id: str
    content: str
    metadata: dict = field(default_factory=dict)
    raw_content: str = ""


# ---------------------------------------------------------------------------
# Document Summary Synthesis (Offline Extractive Summarizer)
# ---------------------------------------------------------------------------

def synthesize_document_summary(raw_docs: List[RawDocument], max_words: int = 70) -> str:
    """
    Synthesize a concise 2-3 sentence document-level summary from raw pages/sections.
    Runs locally with zero external API calls or latency overhead.
    """
    if not raw_docs:
        return "Empty document."

    collected_sentences: List[str] = []
    seen_sentences: set[str] = set()

    # Collect opening text and section headers across the first few pages
    for doc in raw_docs[:5]:
        section = doc.metadata.get("section_title")
        if section and section not in ("Document Start", "Overview", "General", "Full Text"):
            if section not in seen_sentences:
                seen_sentences.add(section)

        # Extract first 2-3 sentences of content
        lines = [line.strip() for line in doc.content.split("\n") if line.strip()]
        for line in lines[:4]:
            if line.startswith("|") or line.startswith("#"):
                continue  # skip raw tables or markdown header tags
            # Split line into sentences
            sentences = re.split(r"(?<=[.!?])\s+", line)
            for s in sentences:
                clean_s = s.strip()
                if len(clean_s) > 25 and clean_s not in seen_sentences:
                    seen_sentences.add(clean_s)
                    collected_sentences.append(clean_s)
                if len(collected_sentences) >= 3:
                    break
        if len(collected_sentences) >= 3:
            break

    if not collected_sentences:
        # Fallback to truncated first content
        first_content = raw_docs[0].content.strip()
        words = first_content.split()[:max_words]
        return " ".join(words) + ("..." if len(first_content.split()) > max_words else "")

    summary = " ".join(collected_sentences)
    words = summary.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words]) + "..."
    return summary


# ---------------------------------------------------------------------------
# Pure-Python Recursive Character Text Splitter Fallback
# ---------------------------------------------------------------------------

class RecursiveTextSplitterFallback:
    """
    Self-contained pure-Python recursive text splitter mirroring LangChain behavior.
    Splits text across separators ['\n\n', '\n', '. ', ' ', ''] respecting token caps.
    """

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        separators: Optional[List[str]] = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

        # Try to use tiktoken for accurate token estimates if available
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def _length(self, text: str) -> int:
        if self._encoder is not None:
            return len(self._encoder.encode(text, disallowed_special=()))
        # Fast approximation: ~4 characters per token
        return max(1, len(text) // 4)

    def split_text(self, text: str) -> List[str]:
        return self._split(text, self.separators)

    def _split(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []
        separator = separators[-1]
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        good_splits: List[str] = []
        for s in splits:
            if self._length(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    merged = self._merge_splits(good_splits, separator)
                    final_chunks.extend(merged)
                    good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    other_info = self._split(s, new_separators)
                    final_chunks.extend(other_info)

        if good_splits:
            merged = self._merge_splits(good_splits, separator)
            final_chunks.extend(merged)

        return final_chunks

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:
        docs: List[str] = []
        current_doc: List[str] = []
        total = 0

        for s in splits:
            _len = self._length(s)
            if total + _len + (self._length(separator) if current_doc else 0) > self.chunk_size:
                if total > 0:
                    doc = separator.join(current_doc).strip()
                    if doc:
                        docs.append(doc)
                    # Handle overlap
                    while total > self.chunk_overlap or (
                        total + _len + (self._length(separator) if current_doc else 0) > self.chunk_size
                        and total > 0
                    ):
                        popped = current_doc.pop(0)
                        total -= self._length(popped) + (self._length(separator) if current_doc else 0)

            current_doc.append(s)
            total += _len + (self._length(separator) if len(current_doc) > 1 else 0)

        doc = separator.join(current_doc).strip()
        if doc:
            docs.append(doc)

        return docs


# ---------------------------------------------------------------------------
# Splitter Factory
# ---------------------------------------------------------------------------

def _get_splitter(chunk_size: int, chunk_overlap: int):
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            model_name="gpt-3.5-turbo",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
    except ImportError:
        return RecursiveTextSplitterFallback(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


# ---------------------------------------------------------------------------
# Public Chunking Pipeline
# ---------------------------------------------------------------------------

def split_documents(
    raw_docs: List[RawDocument],
    chunk_size: int = 800,
    chunk_overlap: int = 150,
    enrich_context: bool = True,
) -> List[TextChunk]:
    """
    Split raw documents into overlapping chunks with contextual breadcrumb enrichment.

    Args:
        raw_docs:       Pages/sections from document loader.
        chunk_size:     Target maximum tokens per chunk.
        chunk_overlap:  Token overlap between adjacent chunks.
        enrich_context: Whether to prepend structural context metadata to each chunk.

    Returns:
        List of TextChunk objects with enriched content and rich metadata.
    """
    if not raw_docs:
        return []

    splitter = _get_splitter(chunk_size, chunk_overlap)
    doc_summary = synthesize_document_summary(raw_docs) if enrich_context else ""

    chunks: List[TextChunk] = []

    for doc in raw_docs:
        pieces = splitter.split_text(doc.content)
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", 1)
        section_title = doc.metadata.get("section_title", "General")
        section_hierarchy = doc.metadata.get("section_hierarchy", [section_title])
        has_tables = doc.metadata.get("has_tables", False)

        for idx, piece in enumerate(pieces):
            clean_piece = piece.strip()
            if not clean_piece:
                continue

            chunk_id = f"{source}_p{page}_c{idx}"

            # Structural Contextual Enrichment
            if enrich_context:
                hierarchy_str = " > ".join(section_hierarchy) if section_hierarchy else section_title
                context_prefix = (
                    f"[Document: {source} | Section: {hierarchy_str} | Context: {doc_summary}]\n\n"
                )
                enriched_content = context_prefix + clean_piece
            else:
                enriched_content = clean_piece

            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    content=enriched_content,
                    raw_content=clean_piece,
                    metadata={
                        **doc.metadata,
                        "chunk_index": idx,
                        "chunk_id": chunk_id,
                        "document_summary": doc_summary,
                        "section_title": section_title,
                        "section_hierarchy": section_hierarchy,
                        "has_tables": has_tables,
                        "enriched": enrich_context,
                    },
                )
            )

    # Attach total_chunks to all chunk metadatas
    total = len(chunks)
    for c in chunks:
        c.metadata["total_chunks"] = total

    logger.info(
        f"[TextSplitter] Split {len(raw_docs)} pages -> {len(chunks)} chunks "
        f"(enriched={enrich_context}, size={chunk_size}, overlap={chunk_overlap})"
    )
    return chunks
