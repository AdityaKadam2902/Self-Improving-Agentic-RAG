"""
Feedback Collector.

Persists user feedback (correct / incorrect) alongside the full RAG
trace so the Failure Analyzer can identify patterns.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from backend.config import get_settings


def _load_db() -> list[dict]:
    path = Path(get_settings().feedback_db_path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_db(records: list[dict]) -> None:
    path = Path(get_settings().feedback_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def record_feedback(
    session_id: str,
    question: str,
    rewritten_query: str,
    answer: str,
    context_chunks: list[dict],
    is_correct: bool,
    verification_verdict: str = "unknown",
) -> str:
    """
    Persist a feedback record.

    Args:
        session_id:           Conversation session identifier.
        question:             Original user question.
        rewritten_query:      Rewritten query used for retrieval.
        answer:               Generated answer.
        context_chunks:       Citation list from BuiltContext.
        is_correct:           User-marked correctness flag.
        verification_verdict: Verdict from the Answer Verifier agent.

    Returns:
        Unique feedback record ID.
    """
    record_id = str(uuid.uuid4())
    record = {
        "id": record_id,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "rewritten_query": rewritten_query,
        "answer": answer,
        "context_chunks": context_chunks,
        "is_correct": is_correct,
        "verification_verdict": verification_verdict,
        "failure_type": None,  # populated by FailureAnalyzer
    }

    db = _load_db()
    db.append(record)
    _save_db(db)

    status = "correct" if is_correct else "INCORRECT"
    logger.info(f"[FeedbackCollector] Recorded {status} feedback → id={record_id}")
    return record_id


def get_incorrect_records(limit: int = 50) -> list[dict]:
    """Return up to *limit* most recent incorrect feedback records."""
    db = _load_db()
    incorrect = [r for r in db if not r.get("is_correct", True)]
    return incorrect[-limit:]


def get_all_records() -> list[dict]:
    """Return the full feedback history."""
    return _load_db()
