"""
Configuration for the backend.

Settings are loaded from environment variables using pydantic-settings,
with graceful fallback to pydantic.BaseModel and os.environ.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field

    class Settings(BaseSettings):
        # LLM
        groq_api_key: str = Field(default="", env="GROQ_API_KEY")
        groq_model: str = Field(default="llama-3.3-70b-versatile", env="GROQ_MODEL")

        # Embeddings & Reranker
        embedding_model: str = Field(
            default="sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL"
        )
        reranker_model: str = Field(
            default="cross-encoder/ms-marco-MiniLM-L-6-v2", env="RERANKER_MODEL"
        )

        # Chunking
        chunk_size: int = Field(default=800, env="CHUNK_SIZE")
        chunk_overlap: int = Field(default=150, env="CHUNK_OVERLAP")

        # Retrieval
        top_k_retrieval: int = Field(default=10, env="TOP_K_RETRIEVAL")
        top_k_rerank: int = Field(default=3, env="TOP_K_RERANK")

        # Vector DB
        vector_backend: str = Field(default="chroma", env="VECTOR_BACKEND")
        chroma_persist_dir: str = Field(default="./vector_db", env="CHROMA_PERSIST_DIR")
        chroma_collection: str = Field(default="rag_documents", env="CHROMA_COLLECTION")

        # Memory
        conversation_history_limit: int = Field(default=5, env="CONVERSATION_HISTORY_LIMIT")

        # Self-improvement
        feedback_db_path: str = Field(default="./vector_db/feedback.json", env="FEEDBACK_DB_PATH")

        # API
        api_host: str = Field(default="0.0.0.0", env="API_HOST")
        api_port: int = Field(default=8000, env="API_PORT")
        cors_origins: List[str] = Field(
            default=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
            env="CORS_ORIGINS",
        )

        model_config = {
            "env_file": ".env",
            "env_file_encoding": "utf-8",
            "extra": "ignore",
        }

except ImportError:
    from pydantic import BaseModel

    class Settings(BaseModel):
        groq_api_key: str = os.getenv("GROQ_API_KEY", "")
        groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        embedding_model: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        reranker_model: str = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
        chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))
        top_k_retrieval: int = int(os.getenv("TOP_K_RETRIEVAL", "10"))
        top_k_rerank: int = int(os.getenv("TOP_K_RERANK", "3"))
        vector_backend: str = os.getenv("VECTOR_BACKEND", "chroma")
        chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", "./vector_db")
        chroma_collection: str = os.getenv("CHROMA_COLLECTION", "rag_documents")
        conversation_history_limit: int = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "5"))
        feedback_db_path: str = os.getenv("FEEDBACK_DB_PATH", "./vector_db/feedback.json")
        api_host: str = os.getenv("API_HOST", "0.0.0.0")
        api_port: int = int(os.getenv("API_PORT", "8000"))
        cors_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()
