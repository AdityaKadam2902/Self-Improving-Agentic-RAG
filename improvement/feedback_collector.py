"""
Feedback Collector.

Persists user feedback (correct / incorrect) alongside the full RAG
trace so the Failure Analyzer can identify patterns.
Backed by transactional SQLite with WAL mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

from backend.config import get_settings
from backend.storage.db import (
    _insert_feedback_sync,
    _get_feedback_records_sync,
    init_database_sync,
)

# Ensure database tables exist
init_database_sync()


def _migrate_legacy_json_if_needed() -> None:
    """Migrate legacy feedback.json records to SQLite WAL if not already migrated."""
    settings = get_settings()
    legacy_path = Path(settings.feedback_db_path)
    if legacy_path.exists():
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            if records and isinstance(records, list):
                existing = _get_feedback_records_sync(limit=1)
                if not existing:
                    logger.info(f"[FeedbackCollector] Migrating {len(records)} legacy JSON records to SQLite WAL...")
                    for r in records:
                        _insert_feedback_sync(
                            session_id=r.get("session_id", "legacy"),
                            query_text=r.get("question", ""),
                            rewritten_query=r.get("rewritten_query", ""),
                            generated_answer=r.get("answer", ""),
                            is_correct=r.get("is_correct", True),
                            context_chunks=r.get("context_chunks", []),
                            verification_verdict=r.get("verification_verdict", "unknown"),
                            record_id=r.get("id"),
                        )
                    logger.success("[FeedbackCollector] Legacy migration complete.")
        except Exception as exc:
            logger.warning(f"[FeedbackCollector] Legacy migration skipped: {exc}")


_migrate_legacy_json_if_needed()


def record_feedback(
    session_id: str,
    question: str,
    rewritten_query: str,
    answer: str,
    context_chunks: list[dict],
    is_correct: bool,
    verification_verdict: str = "unknown",
    grounding_score: float = 1.0,
    latency_ms: float = 0.0,
    token_count: int = 0,
    cost_usd: float = 0.0,
) -> str:
    """
    Persist a feedback record synchronously into the SQLite WAL store.
    """
    record_id = _insert_feedback_sync(
        session_id=session_id,
        query_text=question,
        rewritten_query=rewritten_query,
        generated_answer=answer,
        is_correct=is_correct,
        context_chunks=context_chunks,
        verification_verdict=verification_verdict,
        grounding_score=grounding_score,
        latency_ms=latency_ms,
        token_count=token_count,
        cost_usd=cost_usd,
    )

    status = "correct" if is_correct else "INCORRECT"
    logger.info(f"[FeedbackCollector] Recorded {status} feedback in SQLite WAL -> id={record_id}")
    return record_id


def get_incorrect_records(limit: int = 50) -> list[dict]:
    """Return up to *limit* most recent incorrect feedback records from SQLite."""
    records = _get_feedback_records_sync(limit=limit, incorrect_only=True)
    # Map column names for compatibility with failure analyzer
    formatted: List[Dict[str, Any]] = []
    for r in records:
        formatted.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "question": r["query_text"],
            "rewritten_query": r["rewritten_query"],
            "answer": r["generated_answer"],
            "context_chunks": r["context_chunks"],
            "is_correct": r["is_correct"],
            "verification_verdict": r["verification_verdict"],
            "failure_type": r.get("failure_category"),
        })
    return formatted


def get_all_records(limit: int = 200) -> list[dict]:
    """Return the recent feedback history from SQLite."""
    records = _get_feedback_records_sync(limit=limit, incorrect_only=False)
    formatted: List[Dict[str, Any]] = []
    for r in records:
        formatted.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "question": r["query_text"],
            "rewritten_query": r["rewritten_query"],
            "answer": r["generated_answer"],
            "context_chunks": r["context_chunks"],
            "is_correct": r["is_correct"],
            "verification_verdict": r["verification_verdict"],
            "failure_type": r.get("failure_category"),
        })
    return formatted
