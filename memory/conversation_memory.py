"""
Conversation Memory.

Maintains a per-session rolling window of the last N message pairs.
Stored in-process (dict keyed by session_id); can be backed by Redis for production.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from loguru import logger

from backend.config import get_settings


@dataclass
class ConversationMemory:
    """In-memory conversation history for a single session."""

    session_id: str
    _history: Deque[dict] = field(default_factory=lambda: deque(maxlen=10))

    def add_user_message(self, content: str) -> None:
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._history.append({"role": "assistant", "content": content})

    def get_history(self, limit: int | None = None) -> list[dict]:
        """Return recent messages, capped at *limit* (defaults to settings)."""
        settings = get_settings()
        cap = limit or settings.conversation_history_limit * 2  # pairs
        return list(self._history)[-cap:]

    def clear(self) -> None:
        self._history.clear()


# ── Global registry ───────────────────────────────────────────────────────────

_sessions: dict[str, ConversationMemory] = {}


def get_memory(session_id: str) -> ConversationMemory:
    """Return (or create) the memory store for *session_id*."""
    if session_id not in _sessions:
        _sessions[session_id] = ConversationMemory(session_id=session_id)
        logger.debug(f"[Memory] Created new session: {session_id}")
    return _sessions[session_id]


def clear_memory(session_id: str) -> None:
    """Delete conversation history for *session_id*."""
    if session_id in _sessions:
        del _sessions[session_id]
        logger.info(f"[Memory] Cleared session: {session_id}")
