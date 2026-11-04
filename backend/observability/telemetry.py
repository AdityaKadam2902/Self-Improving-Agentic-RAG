"""
OpenTelemetry and Prometheus Metrics Exporter.

Exposes production metrics in standard Prometheus text format at /metrics:
- rag_requests_total: Counter of queries by route, cache_hit, and verification verdict.
- rag_latency_seconds: Latency summary and histograms.
- rag_tokens_total: Counter of prompt and completion tokens.
- rag_estimated_cost_usd_total: Counter of cumulative USD cost.
- rag_cache_hits_total: Counter of semantic cache hits.
- rag_crag_evaluations_total: Counter of CRAG quality decisions.
- rag_grounding_score: Rolling gauge of claim NLI verification score.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Thread-safe in-memory metric store rendering standard Prometheus text exposition format.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Metrics data structures
        self.requests_total: Dict[Tuple[str, str, str], int] = {}  # (route, cache_hit, verdict) -> count
        self.tokens_total: Dict[str, int] = {"prompt": 0, "completion": 0}
        self.cost_usd_total: float = 0.0
        self.cache_hits_total: int = 0
        self.crag_evaluations_total: Dict[str, int] = {"CORRECT": 0, "AMBIGUOUS": 0, "INCORRECT": 0}

        self.latency_sum_seconds: float = 0.0
        self.latency_count: int = 0
        self.recent_grounding_scores: List[float] = []

    def record_request(
        self,
        route: str,
        cache_hit: bool,
        verification_verdict: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        crag_action: Optional[str] = None,
        grounding_score: Optional[float] = None,
    ) -> None:
        """Record telemetry from a completed RAG request."""
        with self._lock:
            key = (route, "true" if cache_hit else "false", verification_verdict)
            self.requests_total[key] = self.requests_total.get(key, 0) + 1

            self.tokens_total["prompt"] += prompt_tokens
            self.tokens_total["completion"] += completion_tokens
            self.cost_usd_total += cost_usd

            if cache_hit:
                self.cache_hits_total += 1

            latency_sec = latency_ms / 1000.0
            self.latency_sum_seconds += latency_sec
            self.latency_count += 1

            if crag_action:
                self.crag_evaluations_total[crag_action] = (
                    self.crag_evaluations_total.get(crag_action, 0) + 1
                )

            if grounding_score is not None:
                self.recent_grounding_scores.append(grounding_score)
                if len(self.recent_grounding_scores) > 100:
                    self.recent_grounding_scores.pop(0)

    def render_prometheus_metrics(self) -> str:
        """
        Render all counters and histograms in standard Prometheus exposition text format.
        """
        lines = []

        with self._lock:
            # 1. Requests Total
            lines.append("# HELP rag_requests_total Total number of RAG query requests processed.")
            lines.append("# TYPE rag_requests_total counter")
            if not self.requests_total:
                lines.append('rag_requests_total{route="default",cache_hit="false",verdict="none"} 0')
            else:
                for (route, cache_hit, verdict), count in self.requests_total.items():
                    lines.append(
                        f'rag_requests_total{{route="{route}",cache_hit="{cache_hit}",verdict="{verdict}"}} {count}'
                    )

            # 2. Cache Hits Total
            lines.append("# HELP rag_cache_hits_total Total number of semantic vector cache hits.")
            lines.append("# TYPE rag_cache_hits_total counter")
            lines.append(f"rag_cache_hits_total {self.cache_hits_total}")

            # 3. Tokens Total
            lines.append("# HELP rag_tokens_total Total number of LLM tokens consumed.")
            lines.append("# TYPE rag_tokens_total counter")
            for token_type, count in self.tokens_total.items():
                lines.append(f'rag_tokens_total{{type="{token_type}"}} {count}')

            # 4. Cost USD Total
            lines.append("# HELP rag_estimated_cost_usd_total Estimated cumulative inference cost in USD.")
            lines.append("# TYPE rag_estimated_cost_usd_total counter")
            lines.append(f"rag_estimated_cost_usd_total {self.cost_usd_total:.6f}")

            # 5. Latency Summary
            lines.append("# HELP rag_latency_seconds Execution duration of pipeline requests in seconds.")
            lines.append("# TYPE rag_latency_seconds summary")
            lines.append(f"rag_latency_seconds_sum {self.latency_sum_seconds:.4f}")
            lines.append(f"rag_latency_seconds_count {self.latency_count}")

            # 6. CRAG Quality Decisions
            lines.append("# HELP rag_crag_evaluations_total Total Corrective RAG decisions by action.")
            lines.append("# TYPE rag_crag_evaluations_total counter")
            for action, count in self.crag_evaluations_total.items():
                lines.append(f'rag_crag_evaluations_total{{status="{action}"}} {count}')

            # 7. Grounding Score Gauge
            lines.append("# HELP rag_grounding_score Current average NLI claim entailment score.")
            lines.append("# TYPE rag_grounding_score gauge")
            avg_score = (
                sum(self.recent_grounding_scores) / len(self.recent_grounding_scores)
                if self.recent_grounding_scores
                else 1.0
            )
            lines.append(f"rag_grounding_score {avg_score:.3f}")

        return "\n".join(lines) + "\n"


_collector_singleton: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Return singleton instance of MetricsCollector."""
    global _collector_singleton
    if _collector_singleton is None:
        with _collector_lock:
            if _collector_singleton is None:
                _collector_singleton = MetricsCollector()
    return _collector_singleton
