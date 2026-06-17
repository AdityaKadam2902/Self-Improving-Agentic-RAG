"""
RAG pipeline orchestration.

Wires together all agents into a LangGraph state machine:

  understand_query
       ↓
  rewrite_query
       ↓
  retrieve
       ↓
  rerank
       ↓
  build_context
       ↓
  generate_answer
       ↓
  verify_answer ──→ (if hallucination & retries remain) ──→ generate_answer
       ↓
  done

Each stage also writes to a trace dict so the UI can show what happened.
"""

from __future__ import annotations

import time
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from loguru import logger

from backend.agents.query_understanding import understand_query
from backend.agents.query_rewriter import rewrite_query
from backend.agents.retriever import hybrid_retrieve, RetrievedChunk
from backend.agents.reranker import rerank_chunks
from backend.agents.context_builder import build_context, BuiltContext
from backend.agents.answer_generator import generate_answer
from backend.agents.answer_verifier import verify_answer, VerificationResult
from backend.improvement.retrieval_optimizer import get_boosted_keywords, get_optimized_prompt


# LangGraph state

class RAGState(TypedDict):
    # Inputs
    query: str
    session_id: str
    conversation_history: list[dict]

    # Intermediate
    rewritten_query: str
    retrieved_chunks: list[RetrievedChunk]
    reranked_chunks: list[RetrievedChunk]
    context: BuiltContext
    verification: VerificationResult

    # Outputs
    answer: str
    citations: list[dict]
    trace: dict          # Observability log
    token_count: int
    retry_count: int
    latency_ms: float


# Node functions

def _node_understand(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    understanding = understand_query(
        query=state["query"],
        conversation_history=state.get("conversation_history"),
    )
    state["trace"]["query_understanding"] = understanding.model_dump()
    state["trace"]["understand_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    # Keep the understanding object around for the rewrite step
    state["trace"]["_understanding"] = understanding
    return state


def _node_rewrite(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    understanding = state["trace"].pop("_understanding")
    boosted = get_boosted_keywords(state["query"])
    rewritten = rewrite_query(
        original_query=state["query"],
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
    chunks = hybrid_retrieve(state["rewritten_query"])
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


def _node_build_context(state: RAGState) -> RAGState:
    context = build_context(state["reranked_chunks"])
    state["context"] = context
    state["citations"] = context.citations
    state["trace"]["context_preview"] = context.context_text[:300]
    return state


def _node_generate(state: RAGState) -> RAGState:
    t0 = time.perf_counter()
    custom_prompt = get_optimized_prompt()
    answer, tokens = generate_answer(
        query=state["query"],
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
    result = verify_answer(
        query=state["query"],
        answer=state["answer"],
        context=state["context"],
    )
    new_retry = state.get("retry_count", 0)
    if result.verdict == "hallucination":
        new_retry += 1
        logger.warning(f"[Orchestrator] Hallucination detected (attempt {new_retry})")
    return {
        "verification": result,
        "retry_count": new_retry,
        "trace": {
            **state["trace"],
            "verification": result.model_dump(),
            "verify_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    }


def _should_regenerate(state: RAGState) -> str:
    verdict = state["verification"].verdict
    retries = state.get("retry_count", 0)
    if verdict == "hallucination" and retries < 2:
        return "regenerate"
    return "done"


# Build graph

def _build_graph() -> StateGraph:
    graph = StateGraph(RAGState)

    graph.add_node("understand", _node_understand)
    graph.add_node("rewrite", _node_rewrite)
    graph.add_node("retrieve", _node_retrieve)
    graph.add_node("rerank", _node_rerank)
    graph.add_node("build_context", _node_build_context)
    graph.add_node("generate", _node_generate)
    graph.add_node("verify", _node_verify)

    graph.set_entry_point("understand")
    graph.add_edge("understand", "rewrite")
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "build_context")
    graph.add_edge("build_context", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify",
        _should_regenerate,
        {"regenerate": "generate", "done": END},
    )

    return graph.compile()


_rag_graph = _build_graph()


# Public entry point

def run_rag_pipeline(
    query: str,
    session_id: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Run the full RAG pipeline for a user query.

    Args:
        query:                User's question.
        session_id:           Conversation session ID.
        conversation_history: Recent chat turns from ConversationMemory.

    Returns:
        Dict with keys: answer, citations, trace, token_count, latency_ms,
        rewritten_query, verification.
    """
    wall_start = time.perf_counter()

    initial_state: RAGState = {
        "query": query,
        "session_id": session_id,
        "conversation_history": conversation_history or [],
        "rewritten_query": query,
        "retrieved_chunks": [],
        "reranked_chunks": [],
        "context": None,  # type: ignore
        "verification": None,  # type: ignore
        "answer": "",
        "citations": [],
        "trace": {"query": query, "session_id": session_id},
        "token_count": 0,
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

    logger.info(
        f"[Orchestrator] Done | session={session_id} | latency={latency}ms | "
        f"tokens={final_state.get('token_count', 0)}"
    )

    return {
        "answer": final_state["answer"],
        "citations": final_state.get("citations", []),
        "rewritten_query": final_state.get("rewritten_query", query),
        "verification": final_state.get("verification"),
        "trace": final_state.get("trace", {}),
        "token_count": final_state.get("token_count", 0),
        "latency_ms": latency,
    }
