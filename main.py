"""
FastAPI entry point for the backend API.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.config import get_settings
from backend.api.upload import router as upload_router
from backend.api.chat import router as chat_router


# Application factory

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RAG Workspace",
        description=(
            "Document Q&A backend with hybrid retrieval, reranking, "
            "answer verification, and feedback-based improvement."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
   )
    # Request logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            f"{request.method} {request.url.path} → {response.status_code} ({latency}ms)"
        )
        return response

    # Global error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Please check server logs."},
        )

    # Routes
    app.include_router(upload_router)
    app.include_router(chat_router)

    # Health check
    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "healthy", "version": "1.0.0"}

    @app.get("/", tags=["system"])
    async def root():
        return {
            "message": "RAG Workspace API",
            "docs": "/docs",
            "health": "/health",
        }

    logger.info("Backend API started.")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level="info",
    )
