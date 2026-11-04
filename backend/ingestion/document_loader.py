"""
Hierarchical Layout-Aware Document Loader.

Parses PDF, DOCX, Markdown, CSV, TSV, and TXT files with layout and structural awareness:
- Preserves table rows and columns as structured Markdown tables.
- Extracts hierarchical section headings and maintains heading breadcrumbs.
- Tags each page/section with rich metadata (section_hierarchy, has_tables, table_count).
- Implements pure-Python standard-library fallbacks for DOCX and CSV to ensure zero-dependency reliability.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class RawDocument:
    """A single page or structural section of a parsed document."""

    content: str
    metadata: dict = field(default_factory=dict)


def format_table_as_markdown(rows: List[List[Any]]) -> str:
    """
    Format a 2D array of rows into a clean, aligned Markdown table.
    Cleans cell newlines and trims whitespace.
    """
    if not rows:
        return ""

    cleaned_rows: List[List[str]] = []
    for row in rows:
        cleaned_rows.append([str(cell or "").strip().replace("\n", " ").replace("|", "\\|") for cell in row])

    # Filter out empty rows
    cleaned_rows = [r for r in cleaned_rows if any(cell for cell in r)]
    if not cleaned_rows:
        return ""

    num_cols = max(len(r) for r in cleaned_rows)
    # Normalize row lengths
    normalized_rows = [r + [""] * (num_cols - len(r)) for r in cleaned_rows]

    headers = normalized_rows[0]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * num_cols) + " |"
    body_lines = ["| " + " | ".join(r) + " |" for r in normalized_rows[1:]]

    return "\n".join([header_line, sep_line] + body_lines)


def load_document(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """
    Parse an uploaded file and return a list of RawDocument pages/sections
    with layout-preserved tables and section hierarchy metadata.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename, used to determine file type.

    Returns:
        List of RawDocument objects, one per page or logical section.

    Raises:
        ValueError: If the file type is unsupported or corrupted.
    """
    suffix = Path(filename).suffix.lower()
    logger.info(f"[DocumentLoader] Loading document: {filename} ({len(file_bytes)} bytes)")

    if suffix == ".pdf":
        return _load_pdf(file_bytes, filename)
    elif suffix in (".docx", ".doc"):
        return _load_docx(file_bytes, filename)
    elif suffix in (".md", ".markdown"):
        return _load_markdown(file_bytes, filename)
    elif suffix in (".csv", ".tsv"):
        return _load_csv(file_bytes, filename, delimiter="\t" if suffix == ".tsv" else ",")
    elif suffix in (".txt", ".log", ".json", ".yaml", ".yml"):
        return _load_txt(file_bytes, filename)
    else:
        raise ValueError(
            f"Unsupported file type: {suffix!r}. Supported types: PDF, DOCX, MD, CSV, TSV, TXT."
        )


# ---------------------------------------------------------------------------
# PDF Layout and Table Extraction
# ---------------------------------------------------------------------------

def _load_pdf(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """
    Parse PDF using PyMuPDF (fitz) with table layout preservation.
    Extracts tabular data into Markdown tables and detects section headers.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("[DocumentLoader] PyMuPDF (fitz) not installed, falling back to raw byte decode.")
        return _load_txt(file_bytes, filename)

    docs: List[RawDocument] = []
    current_section = "Document Start"
    section_hierarchy: List[str] = [current_section]

    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        total_pages = len(pdf)

        for page_num, page in enumerate(pdf, start=1):
            table_markdowns: List[str] = []
            has_tables = False

            # 1. Attempt table extraction if PyMuPDF table finder is available
            try:
                tables = page.find_tables()
                if tables and tables.tables:
                    for tbl in tables.tables:
                        extracted = tbl.extract()
                        if extracted and len(extracted) > 1:
                            md_table = format_table_as_markdown(extracted)
                            if md_table:
                                table_markdowns.append(md_table)
                                has_tables = True
            except Exception as e:
                logger.debug(f"[DocumentLoader] Table extraction skipped for page {page_num}: {e}")

            # 2. Extract text blocks to identify headers and layout
            page_text = page.get_text("text").strip()
            if not page_text and not table_markdowns:
                continue

            # Check for header patterns in lines (e.g. "1. Introduction", "Section 2:")
            for line in page_text.splitlines()[:5]:
                clean_line = line.strip()
                if clean_line and (
                    re.match(r"^(\d+(\.\d+)*\s+[A-Z][A-Za-z0-9\s]{2,50})$", clean_line)
                    or re.match(r"^(Chapter|Section|Part)\s+\d+", clean_line, re.IGNORECASE)
                ):
                    current_section = clean_line
                    section_hierarchy = [current_section]
                    break

            # 3. Assemble composite layout content
            composite_parts = []
            if page_text:
                composite_parts.append(page_text)
            if table_markdowns:
                composite_parts.append("\n\n### Extracted Tables:\n" + "\n\n".join(table_markdowns))

            full_content = "\n\n".join(composite_parts)

            docs.append(
                RawDocument(
                    content=full_content,
                    metadata={
                        "source": filename,
                        "page": page_num,
                        "total_pages": total_pages,
                        "file_type": "pdf",
                        "section_title": current_section,
                        "section_hierarchy": list(section_hierarchy),
                        "has_tables": has_tables,
                        "table_count": len(table_markdowns),
                        "char_count": len(full_content),
                        "word_count": len(full_content.split()),
                    },
                )
            )

    logger.info(f"[DocumentLoader] PDF loaded: {len(docs)} pages from {filename} (Tables found: {sum(d.metadata.get('table_count', 0) for d in docs)})")
    return docs


# ---------------------------------------------------------------------------
# DOCX Layout and Table Extraction
# ---------------------------------------------------------------------------

def _load_docx(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """
    Parse DOCX file.
    Prefers python-docx if installed, otherwise falls back to pure-Python zipfile + XML parser.
    Preserves table structures as Markdown tables and tracks Heading styles.
    """
    try:
        from docx import Document
        return _load_docx_with_library(file_bytes, filename)
    except ImportError:
        logger.info("[DocumentLoader] python-docx not installed. Using pure-Python XML parser for DOCX.")
        return _load_docx_with_zip(file_bytes, filename)


def _load_docx_with_library(file_bytes: bytes, filename: str) -> List[RawDocument]:
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    sections: List[RawDocument] = []
    current_content: List[str] = []
    current_section = "Introduction"
    section_hierarchy: List[str] = [current_section]
    section_index = 1
    tables_in_section = 0

    # Extract tables mapping
    table_index = 0
    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            para_text = block.text.strip() if hasattr(block, "text") and block.text else ""
            if not para_text:
                continue
            # Look for heading style in paragraph properties
            pPr = block.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr")
            style_name = ""
            if pPr is not None:
                pStyle = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle")
                if pStyle is not None:
                    style_name = pStyle.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")

            if "Heading" in style_name and current_content:
                sections.append(
                    RawDocument(
                        content="\n".join(current_content),
                        metadata={
                            "source": filename,
                            "page": section_index,
                            "file_type": "docx",
                            "section_title": current_section,
                            "section_hierarchy": list(section_hierarchy),
                            "has_tables": tables_in_section > 0,
                            "table_count": tables_in_section,
                            "char_count": sum(len(c) for c in current_content),
                            "word_count": sum(len(c.split()) for c in current_content),
                        },
                    )
                )
                current_content = []
                section_index += 1
                tables_in_section = 0
                current_section = para_text
                section_hierarchy = [current_section]

            current_content.append(para_text)

        elif tag == "tbl":
            # Extract docx table
            if table_index < len(doc.tables):
                t = doc.tables[table_index]
                rows = []
                for row in t.rows:
                    rows.append([cell.text.strip() for cell in row.cells])
                md_table = format_table_as_markdown(rows)
                if md_table:
                    current_content.append("\n" + md_table + "\n")
                    tables_in_section += 1
                table_index += 1

    if current_content:
        sections.append(
            RawDocument(
                content="\n".join(current_content),
                metadata={
                    "source": filename,
                    "page": section_index,
                    "file_type": "docx",
                    "section_title": current_section,
                    "section_hierarchy": list(section_hierarchy),
                    "has_tables": tables_in_section > 0,
                    "table_count": tables_in_section,
                    "char_count": sum(len(c) for c in current_content),
                    "word_count": sum(len(c.split()) for c in current_content),
                },
            )
        )

    logger.info(f"[DocumentLoader] DOCX loaded: {len(sections)} sections from {filename}")
    return sections


def _load_docx_with_zip(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """
    Pure-Python DOCX parser that inspects word/document.xml inside the zip archive.
    Extracts text, detects headings, and parses tables into clean Markdown.
    """
    sections: List[RawDocument] = []
    current_content: List[str] = []
    current_section = "General"
    section_hierarchy: List[str] = [current_section]
    section_index = 1
    tables_in_section = 0

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("Corrupt DOCX file: word/document.xml not found.")
            xml_content = z.read("word/document.xml")

        root = ET.fromstring(xml_content)
        w_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        namespaces = {"w": w_namespace}

        body = root.find("w:body", namespaces)
        if body is None:
            return _load_txt(file_bytes, filename)

        for elem in body:
            tag = elem.tag.split("}")[-1]

            if tag == "p":
                # Paragraph
                texts = [node.text for node in elem.findall(".//w:t", namespaces) if node.text]
                p_text = "".join(texts).strip()
                if not p_text:
                    continue

                # Check heading style
                style_node = elem.find(".//w:pStyle", namespaces)
                style_val = style_node.attrib.get(f"{{{w_namespace}}}val", "") if style_node is not None else ""

                if "Heading" in style_val and current_content:
                    sections.append(
                        RawDocument(
                            content="\n".join(current_content),
                            metadata={
                                "source": filename,
                                "page": section_index,
                                "file_type": "docx",
                                "section_title": current_section,
                                "section_hierarchy": list(section_hierarchy),
                                "has_tables": tables_in_section > 0,
                                "table_count": tables_in_section,
                                "char_count": sum(len(c) for c in current_content),
                                "word_count": sum(len(c.split()) for c in current_content),
                            },
                        )
                    )
                    current_content = []
                    section_index += 1
                    tables_in_section = 0
                    current_section = p_text
                    section_hierarchy = [current_section]

                current_content.append(p_text)

            elif tag == "tbl":
                # Table
                rows: List[List[str]] = []
                for tr in elem.findall("w:tr", namespaces):
                    row: List[str] = []
                    for tc in tr.findall("w:tc", namespaces):
                        cell_texts = [t.text for t in tc.findall(".//w:t", namespaces) if t.text]
                        row.append("".join(cell_texts).strip())
                    if any(row):
                        rows.append(row)

                if rows:
                    md_table = format_table_as_markdown(rows)
                    if md_table:
                        current_content.append("\n" + md_table + "\n")
                        tables_in_section += 1

    except Exception as e:
        logger.warning(f"[DocumentLoader] Pure-python docx parser error: {e}. Falling back to plain text.")
        return _load_txt(file_bytes, filename)

    if current_content:
        sections.append(
            RawDocument(
                content="\n".join(current_content),
                metadata={
                    "source": filename,
                    "page": section_index,
                    "file_type": "docx",
                    "section_title": current_section,
                    "section_hierarchy": list(section_hierarchy),
                    "has_tables": tables_in_section > 0,
                    "table_count": tables_in_section,
                    "char_count": sum(len(c) for c in current_content),
                    "word_count": sum(len(c.split()) for c in current_content),
                },
            )
        )

    return sections


# ---------------------------------------------------------------------------
# Markdown Layout and Header Hierarchy Extraction
# ---------------------------------------------------------------------------

def _load_markdown(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """Parse Markdown files, splitting by top-level headers (# and ##)."""
    text = file_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return []

    lines = text.splitlines()
    sections: List[RawDocument] = []
    current_lines: List[str] = []
    current_section = "Overview"
    hierarchy: List[str] = [current_section]
    section_index = 1

    for line in lines:
        header_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if header_match:
            if current_lines:
                content_str = "\n".join(current_lines).strip()
                if content_str:
                    has_tbl = bool(re.search(r"\|.+\|.+\|", content_str))
                    sections.append(
                        RawDocument(
                            content=content_str,
                            metadata={
                                "source": filename,
                                "page": section_index,
                                "file_type": "md",
                                "section_title": current_section,
                                "section_hierarchy": list(hierarchy),
                                "has_tables": has_tbl,
                                "table_count": 1 if has_tbl else 0,
                                "char_count": len(content_str),
                                "word_count": len(content_str.split()),
                            },
                        )
                    )
                    section_index += 1
                current_lines = []

            level = len(header_match.group(1))
            current_section = header_match.group(2).strip()
            if level == 1:
                hierarchy = [current_section]
            else:
                hierarchy = hierarchy[:level - 1] + [current_section]

        current_lines.append(line)

    if current_lines:
        content_str = "\n".join(current_lines).strip()
        has_tbl = bool(re.search(r"\|.+\|.+\|", content_str))
        sections.append(
            RawDocument(
                content=content_str,
                metadata={
                    "source": filename,
                    "page": section_index,
                    "file_type": "md",
                    "section_title": current_section,
                    "section_hierarchy": list(hierarchy),
                    "has_tables": has_tbl,
                    "table_count": 1 if has_tbl else 0,
                    "char_count": len(content_str),
                    "word_count": len(content_str.split()),
                },
            )
        )

    logger.info(f"[DocumentLoader] Markdown loaded: {len(sections)} sections from {filename}")
    return sections


# ---------------------------------------------------------------------------
# CSV and TSV Layout Extraction
# ---------------------------------------------------------------------------

def _load_csv(file_bytes: bytes, filename: str, delimiter: str = ",") -> List[RawDocument]:
    """Parse CSV or TSV files into clean, structured Markdown tables."""
    text = file_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return []

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not rows:
        return []

    md_table = format_table_as_markdown(rows)
    headers = [str(c).strip() for c in rows[0]]

    return [
        RawDocument(
            content=md_table,
            metadata={
                "source": filename,
                "page": 1,
                "file_type": "csv" if delimiter == "," else "tsv",
                "section_title": f"Tabular Dataset: {filename}",
                "section_hierarchy": [f"Dataset ({len(rows) - 1} rows, {len(headers)} columns)"],
                "has_tables": True,
                "table_count": 1,
                "headers": headers,
                "row_count": len(rows) - 1,
                "char_count": len(md_table),
                "word_count": len(md_table.split()),
            },
        )
    ]


# ---------------------------------------------------------------------------
# Plain Text Extraction
# ---------------------------------------------------------------------------

def _load_txt(file_bytes: bytes, filename: str) -> List[RawDocument]:
    """Parse a plain-text file as a single document with structural analysis."""
    text = file_bytes.decode("utf-8", errors="replace").strip()
    return [
        RawDocument(
            content=text,
            metadata={
                "source": filename,
                "page": 1,
                "file_type": "txt",
                "section_title": "Full Text",
                "section_hierarchy": ["Document Body"],
                "has_tables": False,
                "table_count": 0,
                "char_count": len(text),
                "word_count": len(text.split()),
            },
        )
    ]
