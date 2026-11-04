"""
Token Budget and Latency SLA Controller.

Enforces execution limits, cost tracking in USD, and latency constraints
to prevent unbounded operational spend and service degradation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("budget_controller")


# Standard inference pricing rates for Llama 3.3 70B (per 1,000 tokens)
INPUT_TOKEN_RATE_PER_1K = 0.00059   # $0.59 per 1M tokens
OUTPUT_TOKEN_RATE_PER_1K = 0.00079  # $0.79 per 1M tokens

# Default session constraints
DEFAULT_SESSION_TOKEN_LIMIT = 50000     # 50k tokens per session
DEFAULT_HARD_TOKEN_LIMIT = 100000       # 100k absolute ceiling
DEFAULT_LATENCY_TIMEOUT_MS = 8000.0     # 8 seconds maximum execution SLA


@dataclass
class BudgetStatus:
    allowed: bool
    remaining_tokens: int
    current_session_cost_usd: float
    reason: Optional[str] = None


@dataclass
class UsageTelemetry:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float


class BudgetController:
    """
    Thread-safe tracker managing token allocations, costs, and latencies across sessions.
    """

    def __init__(
        self,
        session_token_limit: int = DEFAULT_SESSION_TOKEN_LIMIT,
        hard_token_limit: int = DEFAULT_HARD_TOKEN_LIMIT,
        max_latency_ms: float = DEFAULT_LATENCY_TIMEOUT_MS,
    ):
        self.session_token_limit = session_token_limit
        self.hard_token_limit = hard_token_limit
        self.max_latency_ms = max_latency_ms
        self._session_usage: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def check_allowance(
        self,
        session_id: str,
        estimated_tokens: int = 500,
    ) -> BudgetStatus:
        """
        Verify whether the session has sufficient token allowance before dispatching queries.
        """
        with self._lock:
            usage = self._session_usage.get(session_id, {
                "total_tokens": 0,
                "cost_usd": 0.0,
                "query_count": 0,
            })

            used_tokens = usage["total_tokens"]
            current_cost = usage["cost_usd"]

            if (used_tokens + estimated_tokens) > self.hard_token_limit:
                logger.warning(
                    f"[BudgetController] Hard token ceiling reached ({used_tokens} >= {self.hard_token_limit}) "
                    f"for session {session_id}"
                )
                return BudgetStatus(
                    allowed=False,
                    remaining_tokens=max(0, self.hard_token_limit - used_tokens),
                    current_session_cost_usd=current_cost,
                    reason="Session token quota exceeded hard operational ceiling.",
                )

            remaining = max(0, self.session_token_limit - used_tokens)
            return BudgetStatus(
                allowed=True,
                remaining_tokens=remaining,
                current_session_cost_usd=current_cost,
            )

    def record_query_usage(
        self,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> UsageTelemetry:
        """
        Record actual token expenditure and latency, calculating cost in USD.
        """
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (
            (prompt_tokens / 1000.0 * INPUT_TOKEN_RATE_PER_1K) +
            (completion_tokens / 1000.0 * OUTPUT_TOKEN_RATE_PER_1K)
        )

        with self._lock:
            if session_id not in self._session_usage:
                self._session_usage[session_id] = {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "query_count": 0,
                    "total_latency_ms": 0.0,
                }

            s = self._session_usage[session_id]
            s["total_tokens"] += total_tokens
            s["prompt_tokens"] += prompt_tokens
            s["completion_tokens"] += completion_tokens
            s["cost_usd"] += cost_usd
            s["query_count"] += 1
            s["total_latency_ms"] += latency_ms

        logger.info(
            f"[BudgetController] Session {session_id[:8]} | tokens={total_tokens} "
            f"(+{prompt_tokens} in, +{completion_tokens} out) | cost=${cost_usd:.6f} | latency={latency_ms:.1f}ms"
        )

        return UsageTelemetry(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 6),
            latency_ms=round(latency_ms, 1),
        )

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Return total historical consumption metrics for a session."""
        with self._lock:
            return dict(self._session_usage.get(session_id, {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
                "query_count": 0,
                "total_latency_ms": 0.0,
            }))

    def reset_session(self, session_id: str) -> None:
        """Reset usage metrics for a session."""
        with self._lock:
            if session_id in self._session_usage:
                del self._session_usage[session_id]


# Global singleton instance
_GLOBAL_BUDGET_CONTROLLER = BudgetController()


def get_budget_controller() -> BudgetController:
    """Return the global budget controller singleton."""
    return _GLOBAL_BUDGET_CONTROLLER
