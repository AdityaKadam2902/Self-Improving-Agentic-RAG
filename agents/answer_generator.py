"""
Answer Generator Agent — with streaming support.
"""

from __future__ import annotations
from loguru import logger
from langchain_groq import ChatGroq
from backend.agents.context_builder import BuiltContext
from backend.config import get_settings

_BASE_SYSTEM_PROMPT = """\
You are a precise and helpful AI assistant that answers questions strictly based on the provided document context.

Rules:
1. Only use information from the provided context.
2. Always cite your sources using the [Source N] labels from the context.
3. If the context does not contain the answer, say: "The provided documents do not contain enough information to answer this question."
4. Do NOT hallucinate or invent facts.
5. Be concise but thorough. Structure the answer clearly.
6. When referencing a source, cite it inline: e.g., "According to [Source 1], ..."
"""


def generate_answer(
    query: str,
    context: BuiltContext,
    conversation_history: list[dict] | None = None,
    custom_system_prompt: str | None = None,
) -> tuple[str, int]:
    """Generate a full answer (non-streaming). Used by verifier."""
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.2,
        max_tokens=1024,
    )
    messages = _build_messages(query, context, conversation_history, custom_system_prompt)
    try:
        response = llm.invoke(messages)
        answer = response.content.strip()
        token_count = response.usage_metadata.get("total_tokens", 0) if response.usage_metadata else 0
        logger.info(f"[AnswerGenerator] Generated answer ({len(answer)} chars, ~{token_count} tokens)")
        return answer, token_count
    except Exception as exc:
        logger.error(f"[AnswerGenerator] LLM call failed: {exc}")
        return f"An error occurred while generating the answer: {exc}", 0


def stream_answer(
    query: str,
    context: BuiltContext,
    conversation_history: list[dict] | None = None,
    custom_system_prompt: str | None = None,
):
    """Stream answer tokens one by one. Yields str chunks."""
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.2,
        max_tokens=1024,
    )
    messages = _build_messages(query, context, conversation_history, custom_system_prompt)
    try:
        for chunk in llm.stream(messages):
            token = chunk.content
            if token:
                yield token
    except Exception as exc:
        logger.error(f"[AnswerGenerator] Stream failed: {exc}")
        yield f"\n\n[Error: {exc}]"


def _build_messages(query, context, conversation_history, custom_system_prompt):
    settings = get_settings()
    system_prompt = custom_system_prompt or _BASE_SYSTEM_PROMPT
    messages = [("system", system_prompt)]
    if conversation_history:
        for msg in conversation_history[-settings.conversation_history_limit:]:
            role = msg.get("role", "human")
            content = msg.get("content", "")
            if role == "user":
                messages.append(("human", content))
            elif role == "assistant":
                messages.append(("ai", content))
    user_msg = (
        f"Context from documents:\n\n{context.context_text}\n\n"
        f"---\n\nQuestion: {query}"
    )
    messages.append(("human", user_msg))
    return messages