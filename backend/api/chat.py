"""
Chat API - Streaming and Feedback Endpoints.

Supports Server-Sent Events (SSE) streaming with non-blocking async execution,
inline security scanning (indirect injection & PII scrubbing), and transactional SQLite storage.
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
from backend.memory.conversation_memory import clear_memory, get_memory
from backend.security.injection_shield import scan_for_injection
from backend.security.pii_scrubber import scrub_pii
from backend.security.tenant_manager import build_vector_tenant_filter

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
    """
    wall_start = time.perf_counter()
    memory = get_memory(session_id)
    history = memory.get_history()

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        # 0. Zero-Trust Security Shield (Injection & PII)
        yield sse("status", {"stage": "Scanning security parameters..."})
        injection_res = scan_for_injection(question, tenant_id=tenant_id)
        pii_res = scrub_pii(injection_res.sanitized_text)
        effective_query = pii_res.redacted_text

        if injection_res.is_suspicious:
            logger.warning(f"[Chat Stream] Query flagged for security check: {injection_res.matched_patterns}")

        # 1. Query Understanding
        yield sse("status", {"stage": "Analyzing query intent..."})
        understanding = understand_query(query=effective_query, conversation_history=history)

        # 2. Query Rewriting
        yield sse("status", {"stage": "Optimizing search query..."})
        boosted = get_boosted_keywords(effective_query)
        rewritten = rewrite_query(
            original_query=effective_query,
            understanding=understanding,
            conversation_history=history,
            boosted_keywords=boosted if boosted else None,
        )

        # 3. Asynchronous Hybrid Retrieval (Threadpool offloaded)
        yield sse("status", {"stage": "Executing hybrid retrieval..."})
        tenant_filter = build_vector_tenant_filter(tenant_id=tenant_id)
        chunks = await async_hybrid_retrieve(rewritten, tenant_filter=tenant_filter)

        # 4. Asynchronous Cross-Encoder Reranking
        yield sse("status", {"stage": "Cross-encoder reranking..."})
        reranked = await async_rerank_chunks(rewritten, chunks)

        # 5. Structured Context Assembly
        context = build_context(reranked)

        # 6. Progressive Answer Streaming
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

        # 7. Verification
        yield sse("status", {"stage": "Verifying grounding & citations..."})
        verification = verify_answer(query=effective_query, answer=full_answer, context=context)

        # Update Session Memory
        memory.add_user_message(question)
        memory.add_assistant_message(full_answer)

        total_latency = round((time.perf_counter() - wall_start) * 1000, 1)

        # Deliver final metadata event
        yield sse("done", {
            "answer": full_answer,
            "citations": context.citations,
            "rewritten_query": rewritten,
            "verification_verdict": verification.verdict,
            "latency_ms": total_latency,
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
