"""
Chat API — with streaming endpoint.
"""

from __future__ import annotations
import uuid
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.orchestrator import run_rag_pipeline
from backend.memory.conversation_memory import get_memory, clear_memory
from backend.improvement.feedback_collector import record_feedback
from backend.improvement.failure_analyzer import run_batch_analysis
from backend.improvement.retrieval_optimizer import run_optimization
from backend.agents.query_understanding import understand_query
from backend.agents.query_rewriter import rewrite_query
from backend.agents.retriever import hybrid_retrieve
from backend.agents.reranker import rerank_chunks
from backend.agents.context_builder import build_context
from backend.agents.answer_generator import stream_answer
from backend.agents.answer_verifier import verify_answer
from backend.improvement.retrieval_optimizer import get_boosted_keywords, get_optimized_prompt

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class FeedbackRequest(BaseModel):
    session_id: str
    question: str
    answer: str
    rewritten_query: str
    citations: list[dict]
    is_correct: bool
    verification_verdict: str = "unknown"


class FeedbackResponse(BaseModel):
    record_id: str
    message: str


async def _stream_rag(question: str, session_id: str):
    """
    Run the RAG pipeline with streaming for the answer step.
    Yields Server-Sent Events (SSE).
    """
    memory = get_memory(session_id)
    history = memory.get_history()

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        # 1. Query understanding
        yield sse("status", {"stage": "Understanding query…"})
        understanding = understand_query(query=question, conversation_history=history)

        # 2. Rewrite
        yield sse("status", {"stage": "Rewriting for retrieval…"})
        boosted = get_boosted_keywords(question)
        rewritten = rewrite_query(
            original_query=question,
            understanding=understanding,
            conversation_history=history,
            boosted_keywords=boosted if boosted else None,
        )

        # 3. Retrieve
        yield sse("status", {"stage": "Searching documents…"})
        chunks = hybrid_retrieve(rewritten)

        # 4. Rerank
        yield sse("status", {"stage": "Reranking results…"})
        reranked = rerank_chunks(rewritten, chunks)

        # 5. Build context
        context = build_context(reranked)

        # 6. Stream answer tokens
        yield sse("status", {"stage": "Generating answer…"})
        custom_prompt = get_optimized_prompt()
        full_answer = ""
        for token in stream_answer(
            query=question,
            context=context,
            conversation_history=history,
            custom_system_prompt=custom_prompt,
        ):
            full_answer += token
            yield sse("token", {"text": token})

        # 7. Verify
        yield sse("status", {"stage": "Verifying…"})
        verification = verify_answer(query=question, answer=full_answer, context=context)

        # Update memory
        memory.add_user_message(question)
        memory.add_assistant_message(full_answer)

        # Send final metadata
        yield sse("done", {
            "answer": full_answer,
            "citations": context.citations,
            "rewritten_query": rewritten,
            "verification_verdict": verification.verdict,
        })

    except Exception as exc:
        logger.error(f"[Chat Stream] Error: {exc}")
        yield sse("error", {"message": str(exc)})


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream a chat response using Server-Sent Events."""
    logger.info(f"[Chat] stream session={request.session_id} question='{request.question[:80]}'")
    return StreamingResponse(
        _stream_rag(request.question, request.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def feedback(request: FeedbackRequest) -> FeedbackResponse:
    record_id = record_feedback(
        session_id=request.session_id,
        question=request.question,
        rewritten_query=request.rewritten_query,
        answer=request.answer,
        context_chunks=request.citations,
        is_correct=request.is_correct,
        verification_verdict=request.verification_verdict,
    )
    status = "correct" if request.is_correct else "incorrect"
    return FeedbackResponse(record_id=record_id, message=f"Feedback recorded as {status}.")


@router.post("/improve")
async def trigger_improvement() -> dict:
    failure_counts = run_batch_analysis()
    optimization_actions = run_optimization()
    return {"status": "complete", "failure_analysis": failure_counts, "optimization": optimization_actions}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict:
    clear_memory(session_id)
    return {"message": f"Session {session_id} cleared."}