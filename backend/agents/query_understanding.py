"""
Query Understanding Agent.

Detects user intent, extracts key entities/keywords, and classifies
the query type to guide downstream agents.
"""

from __future__ import annotations

from langchain_groq import ChatGroq
from loguru import logger
from pydantic import BaseModel, Field

from backend.config import get_settings


class QueryUnderstanding(BaseModel):
    intent: str = Field(description="Detected user intent, e.g. 'factual', 'analytical', 'summarization'")
    keywords: list[str] = Field(description="Important keywords extracted from the query")
    query_type: str = Field(description="One of: factual | analytical | summarization | comparison | unknown")
    complexity: str = Field(description="One of: simple | medium | complex")


_SYSTEM_PROMPT = """\
You are a Query Understanding Agent. Analyze the user query and return a JSON object with:
- intent: the purpose of the query
- keywords: list of important domain-specific terms
- query_type: factual | analytical | summarization | comparison | unknown
- complexity: simple | medium | complex

Return ONLY valid JSON with no extra text.
"""


def understand_query(query: str, conversation_history: list[dict] | None = None) -> QueryUnderstanding:
    """
    Analyze a user query and extract structured understanding.

    Args:
        query: The raw user question.
        conversation_history: Optional list of prior {role, content} dicts.

    Returns:
        QueryUnderstanding pydantic model.
    """
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.0,
        max_tokens=512,
    )

    history_context = ""
    if conversation_history:
        history_context = "\n\nConversation so far:\n" + "\n".join(
            f"  {m['role'].upper()}: {m['content']}" for m in conversation_history[-3:]
        )

    messages = [
        ("system", _SYSTEM_PROMPT),
        ("human", f"Query: {query}{history_context}"),
    ]

    try:
        response = llm.invoke(messages)
        import json, re
        raw = response.content.strip()
        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        data = json.loads(raw)
        result = QueryUnderstanding(**data)
        logger.info(f"[QueryUnderstanding] intent={result.intent} type={result.query_type} complexity={result.complexity}")
        return result
    except Exception as exc:
        logger.warning(f"[QueryUnderstanding] Parse failed ({exc}), using defaults.")
        # Graceful degradation
        return QueryUnderstanding(
            intent="unknown",
            keywords=query.lower().split()[:5],
            query_type="factual",
            complexity="simple",
        )
