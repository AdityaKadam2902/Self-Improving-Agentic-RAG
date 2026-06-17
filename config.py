"""
Configuration for the backend.

Settings are loaded from environment variables using pydantic-settings.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # LLM
    groq_api_key: str = Field(..., env="GROQ_API_KEY")
    groq_model: str = Field("llama-3.3-70b-versatile", env="GROQ_MODEL")

    # Embeddings
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL"
    )
    reranker_model: str = Field(
        "cross-encoder/ms-marco-MiniLM-L-6-v2", env="RERANKER_MODEL"
    )

    # Chunking
    chunk_size: int = Field(800, env="CHUNK_SIZE")
    chunk_overlap: int = Field(150, env="CHUNK_OVERLAP")

    # Retrieval
    top_k_retrieval: int = Field(10, env="TOP_K_RETRIEVAL")
    top_k_rerank: int = Field(3, env="TOP_K_RERANK")

    # Vector DB
    vector_backend: str = Field("chroma", env="VECTOR_BACKEND")  # "chroma" | "qdrant"
    chroma_persist_dir: str = Field("./vector_db", env="CHROMA_PERSIST_DIR")
    chroma_collection: str = Field("rag_documents", env="CHROMA_COLLECTION")

    # Memory
    conversation_history_limit: int = Field(5, env="CONVERSATION_HISTORY_LIMIT")

    # Self-improvement
    feedback_db_path: str = Field("./vector_db/feedback.json", env="FEEDBACK_DB_PATH")

    # API
    api_host: str = Field("0.0.0.0", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
        env="CORS_ORIGINS",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()