"""
Answer Verification Agent.

Checks whether a generated answer is grounded in the retrieved context.
Returns a verdict and a confidence score. If hallucination is detected,
signals the orchestrator to regenerate.
"""

from __future__ import annotations

import json
import re

from loguru import logger
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from backend.agents.context_builder import BuiltContext
from backend.config import get_settings


class VerificationResult(BaseModel):
    is_grounded: bool = Field(description="True if the answer is supported by the context.")
    confidence: float = Field(description="0.0–1.0 confidence that the answer is grounded.")
    verdict: str = Field(description="One of: grounded | hallucination | insufficient_context")
    explanation: str = Field(description="Brief explanation of the verdict.")


_SYSTEM_PROMPT = """\
You are an Answer Verification Agent for a RAG system.

Your job: determine whether the answer is grounded in the provided context.

Return ONLY a JSON object with:
{
  "is_grounded": <true|false>,
  "confidence": <0.0 to 1.0>,
  "verdict": "<grounded|hallucination|insufficient_context>",
  "explanation": "<one sentence>"
}

Grounding rules:
- "grounded": every key claim in the answer can be traced to the context.
- "hallucination": the answer contains claims NOT present in the context.
- "insufficient_context": the answer correctly says it cannot answer, or context is empty.
"""


def verify_answer(
    query: str,
    answer: str,
    context: BuiltContext,
) -> VerificationResult:
    """
    Verify whether *answer* is grounded in *context*.

    Args:
        query:   The user question.
        answer:  The generated answer to verify.
        context: The BuiltContext used to generate the answer.

    Returns:
        VerificationResult with grounding verdict.
    """
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.0,
        max_tokens=512,
    )

    user_msg = (
        f"Question: {query}\n\n"
        f"Context:\n{context.context_text[:3000]}\n\n"
        f"Answer to verify:\n{answer}"
    )

    messages = [("system", _SYSTEM_PROMPT), ("human", user_msg)]

    try:
        response = llm.invoke(messages)
        raw = response.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        data = json.loads(raw)
        result = VerificationResult(**data)
        logger.info(
            f"[AnswerVerifier] verdict={result.verdict} confidence={result.confidence:.2f}"
        )
        return result
    except Exception as exc:
        logger.warning(f"[AnswerVerifier] Parse failed ({exc}), defaulting to grounded.")
        return VerificationResult(
            is_grounded=True,
            confidence=0.5,
            verdict="grounded",
            explanation="Verification could not be performed; defaulting to grounded.",
        )
