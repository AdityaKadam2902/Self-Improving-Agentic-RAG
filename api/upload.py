"""
Document Upload and Ingestion API.

Provides endpoints for document ingestion, collection listing, and deletion.
Includes pre-indexing adversarial injection sanitization and PII scrubbing.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel

from backend.config import get_settings
from backend.ingestion.document_loader import load_document
from backend.ingestion.embedding_generator import (
    embed_and_store,
    get_all_documents,
    get_collection,
)
from backend.ingestion.text_splitter import split_documents
from backend.security.injection_shield import scan_for_injection
from backend.security.pii_scrubber import scrub_pii
from backend.utils.async_executor import run_in_threadpool

router = APIRouter(prefix="/api", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE_MB = 50


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    pages_parsed: int
    security_flags: dict
    message: str


class DocumentInfo(BaseModel):
    source: str
    chunk_count: int


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
) -> UploadResponse:
    """
    Upload, sanitize, and index a document.
    Enforces security scanning (indirect injection & PII scrubbing) and offloads embedding.
    """
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

    logger.info(f"[Upload] Processing '{file.filename}' ({size_mb:.2f} MB) for tenant '{tenant_id}'")

    try:
        settings = get_settings()

        # 1. Parse raw document
        raw_docs = await run_in_threadpool(load_document, file_bytes, file.filename)

        # 2. Security scan & PII scrubbing per page/section
        total_injections = 0
        total_pii_redacted = 0
        for doc in raw_docs:
            inj_res = scan_for_injection(doc.content, tenant_id=tenant_id)
            if inj_res.is_suspicious:
                total_injections += 1
            pii_res = scrub_pii(inj_res.sanitized_text)
            total_pii_redacted += pii_res.redactions_count
            doc.content = pii_res.redacted_text
            doc.metadata["tenant_id"] = tenant_id

        # 3. Split into chunks
        chunks = split_documents(
            raw_docs,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        for c in chunks:
            c.metadata["tenant_id"] = tenant_id

        # 4. Offload embedding generation and vector upsert to worker threadpool
        await run_in_threadpool(embed_and_store, chunks)

        # 5. Invalidate tenant semantic cache so fresh document data is indexed
        from backend.routing.semantic_cache import get_semantic_cache
        get_semantic_cache().invalidate_tenant(tenant_id)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception(f"[Upload] Ingestion failed for '{file.filename}'")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    sec_summary = {
        "adversarial_signatures_neutralized": total_injections,
        "pii_entities_redacted": total_pii_redacted,
    }

    return UploadResponse(
        filename=file.filename,
        chunks_indexed=len(chunks),
        pages_parsed=len(raw_docs),
        security_flags=sec_summary,
        message=f"Successfully indexed {len(chunks)} chunks from {len(raw_docs)} pages.",
    )


@router.get("/documents", response_model=List[DocumentInfo])
async def list_documents() -> List[DocumentInfo]:
    """Return all indexed document sources with their chunk counts."""
    all_ids, all_docs, metadatas = await run_in_threadpool(get_all_documents)

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
    from backend.routing.semantic_cache import get_semantic_cache
    get_semantic_cache().clear()
    logger.info(f"[Upload] Deleted {len(ids_to_delete)} chunks for '{source}' and cleared cache")
    return {"deleted": len(ids_to_delete), "source": source}
