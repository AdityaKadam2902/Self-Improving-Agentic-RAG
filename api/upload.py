"""
Document Upload API.

POST /api/upload  – Accept file, run ingestion pipeline, return status.
GET  /api/documents – List indexed documents.
DELETE /api/documents/{source} – Remove a document from the index.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel

from backend.ingestion.document_loader import load_document
from backend.ingestion.text_splitter import split_documents
from backend.ingestion.embedding_generator import embed_and_store, get_collection, get_all_documents, collection_count
from backend.config import get_settings

router = APIRouter(prefix="/api", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE_MB = 50


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    pages_parsed: int
    message: str


class DocumentInfo(BaseModel):
    source: str
    chunk_count: int


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    """
    Upload and index a document.

    Accepts PDF, DOCX, and TXT files up to 50 MB.
    """
    # ── Validation ────────────────────────────────────────────────────────────
    suffix = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum allowed: {MAX_FILE_SIZE_MB} MB.",
        )

    logger.info(f"[Upload] Processing '{file.filename}' ({size_mb:.2f} MB)")

    # ── Ingestion pipeline ────────────────────────────────────────────────────
    try:
        settings = get_settings()
        raw_docs = load_document(file_bytes, file.filename)
        chunks = split_documents(
            raw_docs,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        embed_and_store(chunks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception(f"[Upload] Ingestion failed for '{file.filename}'")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    return UploadResponse(
        filename=file.filename,
        chunks_indexed=len(chunks),
        pages_parsed=len(raw_docs),
        message=f"Successfully indexed {len(chunks)} chunks from {len(raw_docs)} pages.",
    )


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents() -> list[DocumentInfo]:
    """Return all indexed document sources with their chunk counts."""
    all_ids, all_docs, metadatas = get_all_documents()

    counts: dict[str, int] = {}
    for meta in metadatas:
        src = (meta or {}).get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1

    return [DocumentInfo(source=src, chunk_count=cnt) for src, cnt in sorted(counts.items())]


@router.delete("/documents/{source:path}", status_code=200)
async def delete_document(source: str) -> dict:
    """Remove all chunks belonging to *source* from the vector index."""
    import os
    backend = os.environ.get("VECTOR_BACKEND", "chroma").lower()

    if backend == "qdrant":
        # For qdrant in-memory, we can't easily delete by metadata — return info
        return {"message": "Delete by source not supported in qdrant in-memory mode.", "source": source}

    collection = get_collection()
    result = collection.get(include=["metadatas"])
    ids_to_delete = [
        rid
        for rid, meta in zip(result["ids"], result.get("metadatas") or [])
        if (meta or {}).get("source") == source
    ]

    if not ids_to_delete:
        raise HTTPException(status_code=404, detail=f"Document '{source}' not found.")

    collection.delete(ids=ids_to_delete)
    logger.info(f"[Upload] Deleted {len(ids_to_delete)} chunks for '{source}'")
    return {"deleted": len(ids_to_delete), "source": source}
