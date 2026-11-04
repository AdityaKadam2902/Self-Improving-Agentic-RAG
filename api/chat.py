"""
Chat API - Streaming and Feedback Endpoints.

Supports Server-Sent Events (SSE) streaming with non-blocking async execution,
inline security scanning (indirect injection & PII scrubbing), in-memory semantic caching,
budget enforcement, and transactional SQLite storage.
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.agents.answer_generator import stream_answer
from backend.agents.answer_verifier import verify_answer
from backend.agents.context_builder import build_context
from backend.agents.query_rewriter import rewrite_query
from backend.agents.query_understanding import understand_query
from backend.agents.reranker import async_rerank_chunks
from backend.agents.retriever import async_hybrid_retrieve
from backend.improvement.failure_analyzer import run_batch_analysis
from backend.improvement.feedback_collector import record_feedback
from backend.improvement.retrieval_optimizer import (
    get_boosted_keywords,
    get_optimized_prompt,
    run_optimization,
)
from backend.ingestion.embedding_generator import embed_query
from backend.memory.conversation_memory import clear_memory, get_memory
from backend.routing.adaptive_router import classify_query_route
from backend.routing.budget_controller import get_budget_controller
from backend.routing.semantic_cache import get_semantic_cache
from backend.security.injection_shield import scan_for_injection
from backend.security.pii_scrubber import scrub_pii
from backend.security.tenant_manager import build_vector_tenant_filter
from backend.utils.async_executor import run_in_threadpool

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = Field(default="default")


class FeedbackRequest(BaseModel):
    session_id: str
    question: str
    answer: str
    rewritten_query: str
    citations: list[dict]
    is_correct: bool
    verification_verdict: str = "unknown"
    grounding_score: float = 1.0
    latency_ms: float = 0.0
    token_count: int = 0
    cost_usd: float = 0.0


class FeedbackResponse(BaseModel):
    record_id: str
    message: str


async def _stream_rag(question: str, session_id: str, tenant_id: str = "default"):
    """
    Asynchronous non-blocking generator streaming RAG pipeline tokens via Server-Sent Events (SSE).
    Enforces semantic caching, budget limits, and security guardrails.
    """
    wall_start = time.perf_counter()
    memory = get_memory(session_id)
    history = memory.get_history()

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        # 0. Check Session Token Allowance
        budget_ctrl = get_budget_controller()
        budget_check = budget_ctrl.check_allowance(session_id, estimated_tokens=500)
        if not budget_check.allowed:
            yield sse("error", {"message": budget_check.reason})
            return

        # 1. Zero-Trust Security Shield (Injection & PII)
        yield sse("status", {"stage": "Scanning security parameters..."})
        injection_res = scan_for_injection(question, tenant_id=tenant_id)
        pii_res = scrub_pii(injection_res.sanitized_text)
        effective_query = pii_res.redacted_text

        if injection_res.is_suspicious:
            logger.warning(f"[Chat Stream] Query flagged for security check: {injection_res.matched_patterns}")

        # 2. Semantic Cache Lookup (<40ms, zero LLM cost)
        cache = get_semantic_cache()
        query_emb = None
        try:
            query_emb = await run_in_threadpool(embed_query, effective_query)
            cached_entry = cache.lookup(query_emb, tenant_id=tenant_id)
            if cached_entry:
                yield sse("status", {"stage": "Serving from verified semantic cache..."})
                yield sse("token", {"text": cached_entry.answer})
                total_latency = round((time.perf_counter() - wall_start) * 1000, 1)
                yield sse("done", {
                    "answer": cached_entry.answer,
                    "citations": cached_entry.citations,
                    "rewritten_query": cached_entry.query_text,
                    "verification_verdict": cached_entry.verification_verdict,
                    "latency_ms": total_latency,
                    "cache_hit": True,
                    "cost_usd": 0.0,
                    "security_flags": {
                        "is_suspicious": injection_res.is_suspicious,
                        "pii_redactions": pii_res.redactions_count,
                    },
                })
                return
        except Exception as exc:
            logger.debug(f"[Chat Stream] Semantic cache lookup bypassed: {exc}")

        # 3. Adaptive Intent & Complexity Routing
        yield sse("status", {"stage": "Classifying execution route..."})
        route_decision = classify_query_route(effective_query, conversation_history=history)

        # 4. Query Understanding & Rewriting
        yield sse("status", {"stage": "Analyzing query intent..."})
        understanding = understand_query(query=effective_query, conversation_history=history)

        yield sse("status", {"stage": "Optimizing search query..."})
        boosted = get_boosted_keywords(effective_query)
        rewritten = rewrite_query(
            original_query=effective_query,
            understanding=understanding,
            conversation_history=history,
            boosted_keywords=boosted if boosted else None,
        )

        # 5. Asynchronous Hybrid Retrieval (Threadpool offloaded)
        yield sse("status", {"stage": "Executing hybrid retrieval..."})
        tenant_filter = build_vector_tenant_filter(tenant_id=tenant_id)
        chunks = await async_hybrid_retrieve(rewritten, tenant_filter=tenant_filter)

        # 6. Asynchronous Cross-Encoder Reranking
        yield sse("status", {"stage": "Cross-encoder reranking..."})
        reranked = await async_rerank_chunks(rewritten, chunks)

        # 7. Structured Context Assembly
        context = build_context(reranked)

        # 8. Progressive Answer Streaming
        yield sse("status", {"stage": "Synthesizing answer..."})
        custom_prompt = get_optimized_prompt()
        full_answer = ""
        for token in stream_answer(
            query=effective_query,
            context=context,
            conversation_history=history,
            custom_system_prompt=custom_prompt,
        ):
            full_answer += token
            yield sse("token", {"text": token})

        # 9. Verification
        yield sse("status", {"stage": "Verifying grounding & citations..."})
        verification = verify_answer(query=effective_query, answer=full_answer, context=context)

        # Update Session Memory
        memory.add_user_message(question)
        memory.add_assistant_message(full_answer)

        total_latency = round((time.perf_counter() - wall_start) * 1000, 1)

        # Estimate Token Counts and Record Budget Cost
        estimated_tokens = int(len(full_answer.split()) * 1.33) + int(len(context.context_text.split()) * 1.33)
        prompt_tokens = int(estimated_tokens * 0.75)
        completion_tokens = int(estimated_tokens * 0.25)
        telemetry = budget_ctrl.record_query_usage(
            session_id=session_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=total_latency,
        )

        # Store in Semantic Cache if Grounded
        if verification.verdict == "grounded" and query_emb and full_answer:
            cache.store(
                query_text=effective_query,
                query_embedding=query_emb,
                answer=full_answer,
                citations=context.citations,
                grounding_score=1.0,
                verification_verdict=verification.verdict,
                tenant_id=tenant_id,
            )

        # Deliver final metadata event
        yield sse("done", {
            "answer": full_answer,
            "citations": context.citations,
            "rewritten_query": rewritten,
            "verification_verdict": verification.verdict,
            "latency_ms": total_latency,
            "cache_hit": False,
            "cost_usd": telemetry.estimated_cost_usd,
            "route": route_decision.route,
            "security_flags": {
                "is_suspicious": injection_res.is_suspicious,
                "pii_redactions": pii_res.redactions_count,
            },
        })

    except Exception as exc:
        logger.error(f"[Chat Stream] Execution error: {exc}")
        yield sse("error", {"message": str(exc)})


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream chat response using Server-Sent Events (SSE).
    """
    logger.info(f"[Chat] Stream requested | session={request.session_id} | query='{request.question[:60]}'")
    return StreamingResponse(
        _stream_rag(request.question, request.session_id, request.tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Record user feedback into transactional SQLite WAL storage.
    """
    record_id = record_feedback(
        session_id=request.session_id,
        question=request.question,
        rewritten_query=request.rewritten_query,
        answer=request.answer,
        context_chunks=request.citations,
        is_correct=request.is_correct,
        verification_verdict=request.verification_verdict,
        grounding_score=request.grounding_score,
        latency_ms=request.latency_ms,
        token_count=request.token_count,
        cost_usd=request.cost_usd,
    )
    status = "correct" if request.is_correct else "incorrect"
    return FeedbackResponse(record_id=record_id, message=f"Feedback logged successfully as {status}.")


@router.post("/improve")
async def trigger_improvement() -> dict:
    """
    Execute failure analysis and prompt optimization cycle.
    """
    failure_counts = run_batch_analysis()
    optimization_actions = run_optimization()
    return {
        "status": "complete",
        "failure_analysis": failure_counts,
        "optimization": optimization_actions,
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    """
    Clear session conversation history.
    """
    clear_memory(session_id)
    return {"message": f"Session {session_id} cleared."}
