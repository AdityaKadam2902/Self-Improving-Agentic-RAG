"""
In-Memory Vectorized Semantic Query Cache.

Caches verified query-answer pairs and retrieves them using dense cosine similarity.
Returns responses in under 40ms with zero LLM inference cost when similarity >= 0.96.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("semantic_cache")


@dataclass
class CachedResponse:
    cache_id: str
    query_text: str
    embedding: List[float]
    answer: str
    citations: List[Dict[str, Any]]
    grounding_score: float
    verification_verdict: str
    tenant_id: str
    created_at: float
    ttl_seconds: int = 86400  # 24-hour default TTL

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class SemanticQueryCache:
    """
    Thread-safe in-memory semantic cache partitioned by tenant.
    """

    def __init__(self, default_threshold: float = 0.960):
        self.default_threshold = default_threshold
        self._cache: Dict[str, List[CachedResponse]] = {}  # tenant_id -> list of entries
        self._lock = threading.Lock()

    def lookup(
        self,
        query_embedding: List[float],
        tenant_id: str = "default",
        threshold: Optional[float] = None,
    ) -> Optional[CachedResponse]:
        """
        Search cache for a verified query with cosine similarity >= threshold.
        Returns the closest matching CachedResponse if found and not expired.
        """
        min_sim = threshold if threshold is not None else self.default_threshold

        with self._lock:
            entries = self._cache.get(tenant_id, [])
            if not entries:
                return None

            best_match: Optional[CachedResponse] = None
            best_sim = -1.0
            valid_entries: List[CachedResponse] = []

            for entry in entries:
                if entry.is_expired():
                    continue
                valid_entries.append(entry)

                sim = _cosine_similarity(query_embedding, entry.embedding)
                if sim >= min_sim and sim > best_sim:
                    best_sim = sim
                    best_match = entry

            # Prune expired entries
            self._cache[tenant_id] = valid_entries

            if best_match:
                logger.info(
                    f"[SemanticCache] HIT (similarity: {best_sim:.4f} >= {min_sim}) | "
                    f"query='{best_match.query_text[:50]}'"
                )
                return best_match

        return None

    def store(
        self,
        query_text: str,
        query_embedding: List[float],
        answer: str,
        citations: List[Dict[str, Any]],
        grounding_score: float = 1.0,
        verification_verdict: str = "grounded",
        tenant_id: str = "default",
        ttl_seconds: int = 86400,
    ) -> str:
        """
        Store a verified response in the semantic cache.
        """
        cache_id = str(uuid.uuid4())
        entry = CachedResponse(
            cache_id=cache_id,
            query_text=query_text,
            embedding=query_embedding,
            answer=answer,
            citations=citations,
            grounding_score=grounding_score,
            verification_verdict=verification_verdict,
            tenant_id=tenant_id,
            created_at=time.time(),
            ttl_seconds=ttl_seconds,
        )

        with self._lock:
            if tenant_id not in self._cache:
                self._cache[tenant_id] = []
            self._cache[tenant_id].append(entry)

        logger.info(f"[SemanticCache] STORED entry {cache_id} for tenant '{tenant_id}' (Total: {len(self._cache[tenant_id])})")
        return cache_id

    def invalidate_tenant(self, tenant_id: str = "default") -> int:
        """
        Invalidate all cached queries for a given tenant (e.g. on new document uploads).
        """
        with self._lock:
            count = len(self._cache.get(tenant_id, []))
            self._cache[tenant_id] = []
        logger.info(f"[SemanticCache] Invalidated {count} entries for tenant '{tenant_id}'")
        return count

    def clear(self) -> None:
        """Clear the entire semantic cache across all tenants."""
        with self._lock:
            self._cache.clear()
        logger.info("[SemanticCache] Entire cache cleared.")

    def size(self, tenant_id: Optional[str] = None) -> int:
        """Return total active entries in cache."""
        with self._lock:
            if tenant_id:
                return len(self._cache.get(tenant_id, []))
            return sum(len(v) for v in self._cache.values())


# Global singleton cache instance
_GLOBAL_SEMANTIC_CACHE = SemanticQueryCache()


def get_semantic_cache() -> SemanticQueryCache:
    """Return the global semantic cache singleton."""
    return _GLOBAL_SEMANTIC_CACHE
