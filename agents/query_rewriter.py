"""
Query Rewriting Agent.

Takes the original query + query understanding + optional boosted keywords
from the self-improvement engine and produces a retrieval-optimised query.
"""

from __future__ import annotations

from langchain_groq import ChatGroq
from loguru import logger

from backend.agents.query_understanding import QueryUnderstanding
from backend.config import get_settings


_SYSTEM_PROMPT = """\
You are a Query Rewriting Agent for a Retrieval-Augmented Generation (RAG) system.

Your task is to rewrite the user's query to maximise document retrieval quality.

Rules:
1. Preserve the original intent.
2. Expand abbreviations and resolve pronouns using conversation context.
3. Add relevant synonyms only if they improve retrieval.
4. Keep the rewritten query concise (1-2 sentences).
5. If boosted keywords are provided, incorporate them naturally.
6. Return ONLY the rewritten query string – no explanations, no JSON.
"""


def rewrite_query(
    original_query: str,
    understanding: QueryUnderstanding,
    conversation_history: list[dict] | None = None,
    boosted_keywords: list[str] | None = None,
) -> str:
    """
    Produce a retrieval-optimised version of *original_query*.

    Args:
        original_query:    The raw user question.
        understanding:     Output of the Query Understanding Agent.
        conversation_history: Recent chat turns for context.
        boosted_keywords:  Extra terms injected by the self-improvement engine.

    Returns:
        Rewritten query string.
    """
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.1,
        max_tokens=256,
    )

    history_snippet = ""
    if conversation_history:
        history_snippet = "\n\nRecent conversation:\n" + "\n".join(
            f"  {m['role'].upper()}: {m['content']}" for m in conversation_history[-3:]
        )

    boost_snippet = ""
    if boosted_keywords:
        boost_snippet = f"\n\nBoosted keywords to incorporate: {', '.join(boosted_keywords)}"

    user_msg = (
        f"Original query: {original_query}\n"
        f"Detected intent: {understanding.intent}\n"
        f"Key concepts: {', '.join(understanding.keywords)}\n"
        f"Query type: {understanding.query_type}"
        f"{history_snippet}"
        f"{boost_snippet}"
    )

    messages = [("system", _SYSTEM_PROMPT), ("human", user_msg)]

    try:
        response = llm.invoke(messages)
        rewritten = response.content.strip().strip('"').strip("'")
        logger.info(f"[QueryRewriter] '{original_query}' → '{rewritten}'")
        return rewritten
    except Exception as exc:
        logger.warning(f"[QueryRewriter] Failed ({exc}), using original query.")
        return original_query
