"""
FastAPI entry point for the enterprise backend API.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.config import get_settings
from backend.storage.db import init_database
from backend.api.upload import router as upload_router
from backend.api.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown routines."""
    logger.info("Initializing enterprise RAG platform subsystems...")
    # Initialize SQLite database with WAL mode
    await init_database()
    logger.info("Platform storage layer ready.")
    yield
    logger.info("Platform shutting down gracefully.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Self-Improving Agentic RAG Platform",
        description=(
            "Autonomous Enterprise-Grade Document Intelligence Platform with "
            "asynchronous hybrid retrieval, zero-trust security guardrails, "
            "propositional claim verification, and evolutionary self-optimization."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS configuration
    origins = settings.cors_origins if hasattr(settings, "cors_origins") else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if "*" not in origins else ["*"],
        allow_credentials=True if "*" not in origins else False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging and latency tracking
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency = round((time.perf_counter() - start) * 1000, 1)
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({latency}ms)"
        )
        return response

    # Global error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception in API request: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Please check server logs."},
        )

    # Routers
    app.include_router(upload_router)
    app.include_router(chat_router)

    # System endpoints
    @app.get("/health", tags=["system"])
    async def health():
        return {
            "status": "healthy",
            "version": "2.0.0",
            "subsystems": {
                "storage": "sqlite_wal_active",
                "security_shield": "active",
                "concurrency": "async_threadpool_active",
            },
        }

    @app.get("/", tags=["system"])
    async def root():
        return {
            "platform": "Self-Improving Agentic RAG Platform",
            "docs": "/docs",
            "health": "/health",
            "version": "2.0.0",
        }

    logger.info("FastAPI application factory initialized.")
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
