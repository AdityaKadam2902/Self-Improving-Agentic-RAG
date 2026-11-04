"""
RAG Pipeline Orchestrator with Economic Routing and Semantic Cache.

Manages the LangGraph state machine:
  security_shield
       |
  route_and_cache_check
       |
  understand_query
       |
  rewrite_query
       |
  retrieve (threadpool offloaded)
       |
  rerank (threadpool offloaded)
       |
  build_context
       |
  generate_answer
       |
  verify_answer ---> (if hallucination & retries remain) ---> generate_answer
       |
  done

Provides both synchronous and asynchronous entry points with token budget
enforcement, semantic caching, and full observability telemetry.
"""

from __future__ import annotations

import time
from typing import Annotated, TypedDict, List, Dict, Any, Optional

from langgraph.graph import END, StateGraph
from loguru import logger

from backend.agents.query_understanding import understand_query, QueryUnderstanding
from backend.agents.query_rewriter import rewrite_query
from backend.agents.retriever import hybrid_retrieve, RetrievedChunk
from backend.agents.reranker import rerank_chunks
from backend.agents.crag_evaluator import get_crag_evaluator
from backend.agents.context_builder import build_context, BuiltContext
from backend.agents.answer_generator import generate_answer
from backend.agents.answer_verifier import verify_answer, VerificationResult
from backend.improvement.retrieval_optimizer import get_boosted_keywords, get_optimized_prompt
from backend.ingestion.embedding_generator import embed_query
from backend.routing.adaptive_router import classify_query_route, RouteDecision
from backend.routing.budget_controller import get_budget_controller
from backend.routing.semantic_cache import get_semantic_cache
from backend.security.injection_shield import scan_for_injection
from backend.security.pii_scrubber import scrub_pii
from backend.security.tenant_manager import build_vector_tenant_filter
from backend.utils.async_executor import run_in_threadpool


# LangGraph State Contract

class RAGState(TypedDict):
    # Inputs
    query: str
    sanitized_query: str
    session_id: str
    tenant_id: str
    conversation_history: List[dict]

    # Security & Routing Intermediate
    security_flags: Dict[str, Any]
    route_decision: Dict[str, Any]
    cache_hit: bool
    query_embedding: Optional[List[float]]
    rewritten_query: str
    retrieved_chunks: List[RetrievedChunk]
    reranked_chunks: List[RetrievedChunk]
    crag_result: Optional[Dict[str, Any]]
    context: Optional[BuiltContext]
    verification: Optional[VerificationResult]

    # Outputs
    answer: str
    citations: List[dict]
    trace: Dict[str, Any]
    token_count: int
    cost_usd: float
    retry_count: int
    latency_ms: float


# Node Functions

def _node_security(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    raw_query = state["query"]
    tenant_id = state.get("tenant_id", "default")

    # 1. Indirect Prompt Injection Scan
    injection_res = scan_for_injection(raw_query, tenant_id=tenant_id)

    # 2. PII Scrubbing
    pii_res = scrub_pii(injection_res.sanitized_text)

    state["sanitized_query"] = pii_res.redacted_text
    state["security_flags"] = {
        "is_suspicious": injection_res.is_suspicious,
        "matched_injection_patterns": injection_res.matched_patterns,
        "pii_redactions_count": pii_res.redactions_count,
        "pii_categories": pii_res.categories_found,
    }
    state["trace"]["security"] = state["security_flags"]
    state["trace"]["security_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_route(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    effective_query = state.get("sanitized_query") or state["query"]

    # 1. Classify route tier
    decision = classify_query_route(
        query=effective_query,
        conversation_history=state.get("conversation_history"),
    )
    state["route_decision"] = {
        "route": decision.route,
        "reasoning": decision.reasoning,
        "sub_queries": decision.sub_queries,
        "estimated_complexity": decision.estimated_complexity,
        "requires_retrieval": decision.requires_retrieval,
    }
    state["trace"]["routing"] = state["route_decision"]
    state["trace"]["route_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_understand(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    query_to_process = state.get("sanitized_query") or state["query"]
    understanding = understand_query(
        query=query_to_process,
        conversation_history=state.get("conversation_history"),
    )
    state["trace"]["query_understanding"] = understanding.model_dump()
    state["trace"]["understand_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    state["trace"]["_understanding"] = understanding
    return state


def _node_rewrite(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    understanding = state["trace"].pop("_understanding")
    effective_query = state.get("sanitized_query") or state["query"]
    boosted = get_boosted_keywords(effective_query)
    rewritten = rewrite_query(
        original_query=effective_query,
        understanding=understanding,
        conversation_history=state.get("conversation_history"),
        boosted_keywords=boosted if boosted else None,
    )
    state["rewritten_query"] = rewritten
    state["trace"]["rewritten_query"] = rewritten
    state["trace"]["boosted_keywords"] = boosted
    state["trace"]["rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_retrieve(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    tenant_id = state.get("tenant_id", "default")
    tenant_filter = build_vector_tenant_filter(tenant_id=tenant_id)
    chunks = hybrid_retrieve(state["rewritten_query"], tenant_filter=tenant_filter)
    state["retrieved_chunks"] = chunks
    state["trace"]["retrieved_chunks"] = [
        {"chunk_id": c.chunk_id, "source": c.metadata.get("source"), "rrf_score": c.rrf_score}
        for c in chunks
    ]
    state["trace"]["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_rerank(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    reranked = rerank_chunks(state["rewritten_query"], state["retrieved_chunks"])
    state["reranked_chunks"] = reranked
    state["trace"]["reranked_chunks"] = [
        {"chunk_id": c.chunk_id, "score": c.vector_score}
        for c in reranked
    ]
    state["trace"]["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_crag_eval(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    evaluator = get_crag_evaluator()
    effective_query = (
        state.get("rewritten_query")
        or state.get("sanitized_query")
        or state["query"]
    )
    crag_res = evaluator.evaluate(effective_query, state.get("reranked_chunks", []))

    state["crag_result"] = {
        "action": crag_res.action,
        "confidence": crag_res.confidence,
        "kept_chunks_count": len(crag_res.kept_chunks),
        "discarded_chunks_count": len(crag_res.discarded_chunks),
        "noise_stripped_count": crag_res.noise_stripped_count,
        "evaluations": [
            {
                "chunk_id": e.chunk_id,
                "confidence_score": e.confidence_score,
                "status": e.status,
                "reason": e.reason,
            }
            for e in crag_res.evaluations
        ],
    }
    # Pass forward only verified relevant chunks to build_context
    state["reranked_chunks"] = crag_res.kept_chunks
    state["trace"]["crag"] = state["crag_result"]
    state["trace"]["crag_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_build_context(state: RAGState) -> RAGState:
    context = build_context(state["reranked_chunks"])
    state["context"] = context
    state["citations"] = context.citations
    state["trace"]["context_preview"] = context.context_text[:300]
    return state


def _node_generate(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    crag_res = state.get("crag_result") or {}

    # If CRAG determined all retrieved chunks were irrelevant distractors, abort ungrounded generation
    if crag_res.get("action") == "INCORRECT" and not state.get("reranked_chunks"):
        state["answer"] = (
            "I reviewed the uploaded documentation, but found no relevant information to answer "
            "your request. Please provide relevant documents or refine your query."
        )
        state["token_count"] = 0
        state["trace"]["answer_preview"] = state["answer"][:300]
        state["trace"]["tokens"] = 0
        state["trace"]["generate_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return state

    custom_prompt = get_optimized_prompt()
    effective_query = state.get("sanitized_query") or state["query"]
    answer, tokens = generate_answer(
        query=effective_query,
        context=state["context"],
        conversation_history=state.get("conversation_history"),
        custom_system_prompt=custom_prompt,
    )
    state["answer"] = answer
    state["token_count"] = tokens
    state["trace"]["answer_preview"] = answer[:300]
    state["trace"]["tokens"] = tokens
    state["trace"]["generate_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return state


def _node_verify(state: RAGState) -> dict:
    t0 = time.perf_counter()
    effective_query = state.get("sanitized_query") or state["query"]
    result = verify_answer(
        query=effective_query,
        answer=state["answer"],
        context=state["context"],
    )
    new_retry = state.get("retry_count", 0)
    if result.verdict == "hallucination":
        new_retry += 1
        logger.warning(f"[Orchestrator] Hallucination detected (attempt {new_retry})")

    citations = result.attributed_citations if result.attributed_citations else state.get("citations", [])
    return {
        "verification": result,
        "citations": citations,
        "retry_count": new_retry,
        "trace": {
            **state["trace"],
            "verification": result.model_dump(),
            "verify_ms": round((time.perf_counter() - t0) * 1000, 1),
        },
    }


def _should_regenerate(state: RAGState) -> str:
    verdict = state["verification"].verdict if state.get("verification") else "grounded"
    retries = state.get("retry_count", 0)
    if verdict == "hallucination" and retries < 2:
        return "regenerate"
    return "done"


# Graph Compilation

def _build_graph() -> StateGraph:
    graph = StateGraph(RAGState)

    graph.add_node("security", _node_security)
    graph.add_node("route", _node_route)
    graph.add_node("understand", _node_understand)
    graph.add_node("rewrite", _node_rewrite)
    graph.add_node("retrieve", _node_retrieve)
    graph.add_node("rerank", _node_rerank)
    graph.add_node("crag_eval", _node_crag_eval)
    graph.add_node("build_context", _node_build_context)
    graph.add_node("generate", _node_generate)
    graph.add_node("verify", _node_verify)

    graph.set_entry_point("security")
    graph.add_edge("security", "route")
    graph.add_edge("route", "understand")
    graph.add_edge("understand", "rewrite")
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "crag_eval")
    graph.add_edge("crag_eval", "build_context")
    graph.add_edge("build_context", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify",
        _should_regenerate,
        {"regenerate": "generate", "done": END},
    )

    return graph.compile()


_rag_graph = _build_graph()


# Public APIs

def run_rag_pipeline(
    query: str,
    session_id: str,
    conversation_history: Optional[List[dict]] = None,
    tenant_id: str = "default",
) -> dict:
    """
    Run the full RAG pipeline for a user query synchronously.
    Enforces token budgeting, semantic caching, and telemetry recording.
    """
    wall_start = time.perf_counter()

    # 1. Check budget allowance
    budget_ctrl = get_budget_controller()
    budget_check = budget_ctrl.check_allowance(session_id, estimated_tokens=500)
    if not budget_check.allowed:
        return {
            "answer": f"Request blocked: {budget_check.reason}",
            "citations": [],
            "cache_hit": False,
            "token_count": 0,
            "cost_usd": 0.0,
            "latency_ms": 0.0,
            "security_flags": {},
            "trace": {"error": budget_check.reason},
        }

    # 2. Semantic Cache Lookup (<40ms)
    cache = get_semantic_cache()
    query_emb: Optional[List[float]] = None
    try:
        query_emb = embed_query(query)
        cached_entry = cache.lookup(query_emb, tenant_id=tenant_id)
        if cached_entry:
            latency = round((time.perf_counter() - wall_start) * 1000, 1)
            logger.info(f"[Orchestrator] Cache Hit served in {latency}ms for query='{query[:50]}'")
            return {
                "answer": cached_entry.answer,
                "citations": cached_entry.citations,
                "rewritten_query": cached_entry.query_text,
                "verification": {"verdict": cached_entry.verification_verdict},
                "cache_hit": True,
                "token_count": 0,
                "cost_usd": 0.0,
                "latency_ms": latency,
                "security_flags": {},
                "trace": {"cache_hit": True, "total_latency_ms": latency},
            }
    except Exception as exc:
        logger.debug(f"[Orchestrator] Cache lookup skipped ({exc})")

    # 3. Execution via LangGraph Pipeline
    initial_state: RAGState = {
        "query": query,
        "sanitized_query": query,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "conversation_history": conversation_history or [],
        "security_flags": {},
        "route_decision": {},
        "cache_hit": False,
        "query_embedding": query_emb,
        "rewritten_query": query,
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "crag_result": None,
        "context": None,
        "verification": None,
        "answer": "",
        "citations": [],
        "trace": {"query": query, "session_id": session_id, "tenant_id": tenant_id},
        "token_count": 0,
        "cost_usd": 0.0,
        "retry_count": 0,
        "latency_ms": 0.0,
    }

    try:
        final_state = _rag_graph.invoke(initial_state)
    except Exception as exc:
        logger.error(f"[Orchestrator] Pipeline error: {exc}")
        final_state = {
            **initial_state,
            "answer": f"Pipeline error: {exc}",
            "citations": [],
        }

    latency = round((time.perf_counter() - wall_start) * 1000, 1)
    final_state["latency_ms"] = latency
    final_state["trace"]["total_latency_ms"] = latency

    # 4. Record token expenditure and cost in budget controller
    tokens_used = final_state.get("token_count", 0)
    prompt_tokens = int(tokens_used * 0.75)
    completion_tokens = int(tokens_used * 0.25)
    telemetry = budget_ctrl.record_query_usage(
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency,
    )
    cost_usd = telemetry.estimated_cost_usd

    # 5. Populate Semantic Cache on verified grounded answers
    verdict = final_state.get("verification")
    is_grounded = verdict.verdict == "grounded" if verdict else True
    if is_grounded and query_emb and final_state.get("answer"):
        cache.store(
            query_text=query,
            query_embedding=query_emb,
            answer=final_state["answer"],
            citations=final_state.get("citations", []),
            grounding_score=1.0,
            verification_verdict=verdict.verdict if verdict else "grounded",
            tenant_id=tenant_id,
        )

    logger.info(
        f"[Orchestrator] Completed | session={session_id} | latency={latency}ms | "
        f"tokens={tokens_used} | cost=${cost_usd:.6f}"
    )

    return {
        "answer": final_state["answer"],
        "citations": final_state.get("citations", []),
        "rewritten_query": final_state.get("rewritten_query", query),
        "verification": final_state.get("verification"),
        "trace": final_state.get("trace", {}),
        "token_count": tokens_used,
        "cost_usd": cost_usd,
        "latency_ms": latency,
        "cache_hit": False,
        "security_flags": final_state.get("security_flags", {}),
        "route_decision": final_state.get("route_decision", {}),
        "crag_result": final_state.get("crag_result", {}),
    }


async def run_rag_pipeline_async(
    query: str,
    session_id: str,
    conversation_history: Optional[List[dict]] = None,
    tenant_id: str = "default",
) -> dict:
    """
    Asynchronous non-blocking wrapper running the pipeline inside the worker threadpool.
    """
    return await run_in_threadpool(
        run_rag_pipeline,
        query=query,
        session_id=session_id,
        conversation_history=conversation_history,
        tenant_id=tenant_id,
    )
