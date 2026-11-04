"""
Document loading pipeline.

Supports PDF, DOCX, and TXT files. Returns a list of raw page-level
Document objects with rich metadata.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from loguru import logger


@dataclass
class RawDocument:
    """A single page/section of a parsed document."""

    content: str
    metadata: dict = field(default_factory=dict)


def load_document(file_bytes: bytes, filename: str) -> list[RawDocument]:
    """
    Parse an uploaded file and return a list of RawDocument pages/sections.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename, used to determine file type.

    Returns:
        List of RawDocument objects, one per page/section.

    Raises:
        ValueError: If the file type is unsupported.
    """
    suffix = Path(filename).suffix.lower()
    logger.info(f"Loading document: {filename} ({len(file_bytes)} bytes)")

    if suffix == ".pdf":
        return _load_pdf(file_bytes, filename)
    elif suffix == ".docx":
        return _load_docx(file_bytes, filename)
    elif suffix == ".txt":
        return _load_txt(file_bytes, filename)
    else:
        raise ValueError(f"Unsupported file type: {suffix!r}. Use PDF, DOCX, or TXT.")


# ── Private helpers ───────────────────────────────────────────────────────────

def _load_pdf(file_bytes: bytes, filename: str) -> list[RawDocument]:
    """Parse a PDF with PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    docs: list[RawDocument] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for page_num, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            docs.append(
                RawDocument(
                    content=text,
                    metadata={
                        "source": filename,
                        "page": page_num,
                        "total_pages": len(pdf),
                        "file_type": "pdf",
                    },
                )
            )

    logger.info(f"PDF loaded: {len(docs)} pages with text from {filename}")
    return docs


def _load_docx(file_bytes: bytes, filename: str) -> list[RawDocument]:
    """Parse a DOCX file, grouping paragraphs into logical sections."""
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    sections: list[RawDocument] = []
    current_chunks: list[str] = []
    section_index = 1

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # treat headings as section separators
        if para.style.name.startswith("Heading") and current_chunks:
            sections.append(
                RawDocument(
                    content="\n".join(current_chunks),
                    metadata={
                        "source": filename,
                        "page": section_index,
                        "file_type": "docx",
                    },
                )
            )
            current_chunks = []
            section_index += 1
        current_chunks.append(text)

    if current_chunks:
        sections.append(
            RawDocument(
                content="\n".join(current_chunks),
                metadata={
                    "source": filename,
                    "page": section_index,
                    "file_type": "docx",
                },
            )
        )

    logger.info(f"DOCX loaded: {len(sections)} sections from {filename}")
    return sections


def _load_txt(file_bytes: bytes, filename: str) -> list[RawDocument]:
    """Parse a plain-text file as a single document."""
    text = file_bytes.decode("utf-8", errors="replace").strip()
    logger.info(f"TXT loaded: {len(text)} chars from {filename}")
    return [
        RawDocument(
            content=text,
            metadata={"source": filename, "page": 1, "file_type": "txt"},
        )
    ]
