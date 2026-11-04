"""
Unit tests for the Economic Routing Engine and Semantic Query Cache (Phase 2).
"""

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.routing.semantic_cache import SemanticQueryCache, _cosine_similarity
from backend.routing.budget_controller import BudgetController
from backend.routing.adaptive_router import classify_query_route


def test_cosine_similarity_calculation():
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]
    vec_c = [0.0, 1.0, 0.0]

    assert math.isclose(_cosine_similarity(vec_a, vec_b), 1.0, rel_tol=1e-5)
    assert math.isclose(_cosine_similarity(vec_a, vec_c), 0.0, rel_tol=1e-5)


def test_semantic_cache_hit_and_miss():
    cache = SemanticQueryCache(default_threshold=0.960)

    query_emb = [0.5, 0.5, 0.5, 0.5]
    cache.store(
        query_text="What are the company holiday days?",
        query_embedding=query_emb,
        answer="The company observes 11 paid holidays per calendar year.",
        citations=[{"source": "Handbook.pdf", "page": 4}],
        grounding_score=0.98,
        tenant_id="tenant_alpha",
    )

    # Identical query embedding should register a cache hit
    cached_hit = cache.lookup(query_emb, tenant_id="tenant_alpha")
    assert cached_hit is not None
    assert cached_hit.answer == "The company observes 11 paid holidays per calendar year."
    assert len(cached_hit.citations) == 1

    # Cross-tenant check: Should NOT hit from tenant_beta
    cross_tenant_miss = cache.lookup(query_emb, tenant_id="tenant_beta")
    assert cross_tenant_miss is None

    # Orthogonal query embedding should register a cache miss
    orthogonal_emb = [-0.5, -0.5, 0.5, 0.5]
    cached_miss = cache.lookup(orthogonal_emb, tenant_id="tenant_alpha")
    assert cached_miss is None


def test_semantic_cache_tenant_invalidation():
    cache = SemanticQueryCache(default_threshold=0.960)
    query_emb = [1.0, 0.0, 0.0]

    cache.store("Test query", query_emb, "Test answer", [], tenant_id="tenant_to_clear")
    assert cache.lookup(query_emb, tenant_id="tenant_to_clear") is not None

    invalidated_count = cache.invalidate_tenant("tenant_to_clear")
    assert invalidated_count == 1
    assert cache.lookup(query_emb, tenant_id="tenant_to_clear") is None


def test_budget_controller_expenditure_and_ceiling():
    controller = BudgetController(session_token_limit=1000, hard_token_limit=2000)

    # Check initial allowance
    status = controller.check_allowance("session_123", estimated_tokens=100)
    assert status.allowed is True

    # Record usage of 1,500 tokens (exceeds session limit, below hard limit)
    telemetry = controller.record_query_usage(
        session_id="session_123",
        prompt_tokens=1000,
        completion_tokens=500,
        latency_ms=1200.0,
    )

    assert telemetry.total_tokens == 1500
    assert telemetry.estimated_cost_usd > 0.0001
    assert telemetry.latency_ms == 1200.0

    # Next query requesting 600 tokens should trip the hard ceiling (1500 + 600 > 2000)
    hard_check = controller.check_allowance("session_123", estimated_tokens=600)
    assert hard_check.allowed is False
    assert "exceeded hard operational ceiling" in (hard_check.reason or "")


def test_adaptive_router_classification():
    # Direct conversational
    decision_direct = classify_query_route("Hello, how are you today?")
    assert decision_direct.route == "direct"
    assert decision_direct.requires_retrieval is False

    # Multi-hop comparative
    decision_multi = classify_query_route("Compare the Q2 software revenue versus the Q3 cloud revenue")
    assert decision_multi.route == "multi_hop"
    assert decision_multi.requires_retrieval is True
    assert len(decision_multi.sub_queries) >= 2

    # Single-hop standard
    decision_single = classify_query_route("What is the maximum deductible for personal health insurance?")
    assert decision_single.route == "single_hop"
    assert decision_single.requires_retrieval is True
