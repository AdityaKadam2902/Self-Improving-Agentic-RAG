"""
Transactional SQLite Storage Manager with Write-Ahead Logging (WAL) Mode.

Replaces flat JSON persistence with a concurrent-safe, relational database.
Provides threadpool-isolated async database operations.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("storage_db")

from backend.config import get_settings
from backend.utils.async_executor import run_in_threadpool


def _get_db_path() -> Path:
    settings = get_settings()
    persist_dir = Path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    return persist_dir / "app_state.db"


_db_initialized = False

def _create_raw_connection() -> sqlite3.Connection:
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_database_sync() -> None:
    """Initialize all schema tables synchronously."""
    global _db_initialized
    conn = _create_raw_connection()
    try:
        with conn:
            # 1. Sessions Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. Feedback and Verification Audit Ledger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_ledger (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    query_text TEXT NOT NULL,
                    rewritten_query TEXT,
                    generated_answer TEXT NOT NULL,
                    grounding_score REAL NOT NULL DEFAULT 1.0,
                    is_correct INTEGER NOT NULL,
                    failure_category TEXT,
                    latency_ms REAL NOT NULL DEFAULT 0.0,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    verification_verdict TEXT DEFAULT 'unknown',
                    context_chunks_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_correct ON feedback_ledger(is_correct);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_session ON feedback_ledger(session_id);")

            # 3. Parameter and System Prompt Versions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parameter_versions (
                    version_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    system_prompt TEXT NOT NULL,
                    parameters TEXT,
                    eval_score REAL DEFAULT 0.0,
                    rrf_k_constant INTEGER NOT NULL DEFAULT 60,
                    rerank_threshold REAL NOT NULL DEFAULT 0.0,
                    faithfulness_score REAL,
                    context_recall_score REAL,
                    is_active INTEGER DEFAULT 0
                );
            """)
            try:
                conn.execute("ALTER TABLE parameter_versions ADD COLUMN parameters TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE parameter_versions ADD COLUMN eval_score REAL DEFAULT 0.0;")
            except Exception:
                pass

            # 4. Security Incident Audit Log
            conn.execute("""
                CREATE TABLE IF NOT EXISTS security_audit_log (
                    incident_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tenant_id TEXT DEFAULT 'default',
                    incident_type TEXT NOT NULL,
                    offending_payload TEXT NOT NULL,
                    action_taken TEXT NOT NULL
                );
            """)
        _db_initialized = True
        logger.info(f"[Database] SQLite WAL database initialized at {_get_db_path()}")
    finally:
        conn.close()


def _get_connection() -> sqlite3.Connection:
    """Create a connection with WAL mode and row factory enabled."""
    global _db_initialized
    if not _db_initialized:
        init_database_sync()
    return _create_raw_connection()


async def init_database() -> None:
    """Asynchronously initialize database tables."""
    await run_in_threadpool(init_database_sync)


# ---------------------------------------------------------------------------
# Sessions Operations
# ---------------------------------------------------------------------------

def _upsert_session_sync(session_id: str, tenant_id: str = "default") -> None:
    conn = _get_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO sessions (session_id, tenant_id, last_active)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET last_active=CURRENT_TIMESTAMP;
            """, (session_id, tenant_id))
    finally:
        conn.close()


async def upsert_session(session_id: str, tenant_id: str = "default") -> None:
    await run_in_threadpool(_upsert_session_sync, session_id, tenant_id)


# ---------------------------------------------------------------------------
# Feedback Operations
# ---------------------------------------------------------------------------

def _insert_feedback_sync(
    session_id: str,
    query_text: str,
    rewritten_query: str,
    generated_answer: str,
    is_correct: bool,
    context_chunks: List[Dict[str, Any]],
    verification_verdict: str = "unknown",
    grounding_score: float = 1.0,
    latency_ms: float = 0.0,
    token_count: int = 0,
    cost_usd: float = 0.0,
    record_id: Optional[str] = None,
) -> str:
    rid = record_id or str(uuid.uuid4())
    _upsert_session_sync(session_id)

    conn = _get_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO feedback_ledger (
                    id, session_id, query_text, rewritten_query,
                    generated_answer, grounding_score, is_correct,
                    verification_verdict, latency_ms, token_count,
                    cost_usd, context_chunks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                rid, session_id, query_text, rewritten_query,
                generated_answer, grounding_score, 1 if is_correct else 0,
                verification_verdict, latency_ms, token_count,
                cost_usd, json.dumps(context_chunks, ensure_ascii=False)
            ))
        return rid
    finally:
        conn.close()


async def insert_feedback(
    session_id: str,
    query_text: str,
    rewritten_query: str,
    generated_answer: str,
    is_correct: bool,
    context_chunks: List[Dict[str, Any]],
    verification_verdict: str = "unknown",
    grounding_score: float = 1.0,
    latency_ms: float = 0.0,
    token_count: int = 0,
    cost_usd: float = 0.0,
) -> str:
    return await run_in_threadpool(
        _insert_feedback_sync,
        session_id=session_id,
        query_text=query_text,
        rewritten_query=rewritten_query,
        generated_answer=generated_answer,
        is_correct=is_correct,
        context_chunks=context_chunks,
        verification_verdict=verification_verdict,
        grounding_score=grounding_score,
        latency_ms=latency_ms,
        token_count=token_count,
        cost_usd=cost_usd,
    )


def _get_feedback_records_sync(limit: int = 100, incorrect_only: bool = False) -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        query = "SELECT * FROM feedback_ledger"
        if incorrect_only:
            query += " WHERE is_correct = 0"
        query += " ORDER BY created_at DESC LIMIT ?;"

        rows = conn.execute(query, (limit,)).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["is_correct"] = bool(d["is_correct"])
            try:
                d["context_chunks"] = json.loads(d.get("context_chunks_json", "[]"))
            except Exception:
                d["context_chunks"] = []
            results.append(d)
        return results
    finally:
        conn.close()


async def get_feedback_records(limit: int = 100, incorrect_only: bool = False) -> List[Dict[str, Any]]:
    return await run_in_threadpool(_get_feedback_records_sync, limit, incorrect_only)


def _update_feedback_failure_category_sync(record_id: str, failure_category: str) -> None:
    conn = _get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE feedback_ledger SET failure_category = ? WHERE id = ?;",
                (failure_category, record_id)
            )
    finally:
        conn.close()


async def update_feedback_failure_category(record_id: str, failure_category: str) -> None:
    await run_in_threadpool(_update_feedback_failure_category_sync, record_id, failure_category)


# ---------------------------------------------------------------------------
# Security Audit Operations
# ---------------------------------------------------------------------------

def _log_security_incident_sync(
    incident_type: str,
    offending_payload: str,
    action_taken: str,
    tenant_id: str = "default",
) -> str:
    incident_id = str(uuid.uuid4())
    conn = _get_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO security_audit_log (
                    incident_id, tenant_id, incident_type,
                    offending_payload, action_taken
                ) VALUES (?, ?, ?, ?, ?);
            """, (incident_id, tenant_id, incident_type, offending_payload[:2000], action_taken))
        logger.warning(f"[SecurityAudit] Incident logged: {incident_type} (ID: {incident_id})")
        return incident_id
    finally:
        conn.close()


async def log_security_incident(
    incident_type: str,
    offending_payload: str,
    action_taken: str,
    tenant_id: str = "default",
) -> str:
    return await run_in_threadpool(
        _log_security_incident_sync,
        incident_type,
        offending_payload,
        action_taken,
        tenant_id,
    )


# ---------------------------------------------------------------------------
# Parameter Versioning & System Evolution
# ---------------------------------------------------------------------------

def _save_parameter_version_sync(
    version_id: str,
    parameters: Dict[str, Any],
    eval_score: float,
    is_active: bool = False,
) -> None:
    conn = _get_connection()
    try:
        with conn:
            if is_active:
                conn.execute("UPDATE parameter_versions SET is_active = 0;")
            prompt = str(parameters.get("boosted_prompt") or "")
            conn.execute("""
                INSERT OR REPLACE INTO parameter_versions (
                    version_id, system_prompt, parameters, eval_score, is_active
                ) VALUES (?, ?, ?, ?, ?);
            """, (
                version_id,
                prompt,
                json.dumps(parameters, ensure_ascii=False),
                eval_score,
                1 if is_active else 0,
            ))
    finally:
        conn.close()


def save_parameter_version(
    version_id: str,
    parameters: Dict[str, Any],
    eval_score: float,
    is_active: bool = False,
) -> None:
    _save_parameter_version_sync(version_id, parameters, eval_score, is_active)


def _get_active_parameter_version_sync() -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    try:
        row = conn.execute("""
            SELECT * FROM parameter_versions WHERE is_active = 1
            ORDER BY created_at DESC LIMIT 1;
        """).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["parameters"] = json.loads(d["parameters"])
        except Exception:
            pass
        return d
    finally:
        conn.close()


def get_active_parameter_version() -> Optional[Dict[str, Any]]:
    return _get_active_parameter_version_sync()
