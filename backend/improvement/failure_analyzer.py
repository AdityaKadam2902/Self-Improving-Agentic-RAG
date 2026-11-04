"""
Failure Analyzer Agent.

Classifies incorrect feedback records into failure types:
  - bad_retrieval:  The context did not contain the answer.
  - hallucination:  The LLM fabricated information.
  - prompt_issue:   The prompt caused the LLM to misinterpret the task.
"""

from __future__ import annotations

import json
import re

from loguru import logger
from langchain_groq import ChatGroq

from backend.config import get_settings
from backend.improvement.feedback_collector import get_incorrect_records, _load_db, _save_db


_SYSTEM_PROMPT = """\
You are a RAG Failure Analyzer. Given a question, the retrieved context, and a wrong answer,
classify the failure type.

Return ONLY a JSON object:
{
  "failure_type": "<bad_retrieval|hallucination|prompt_issue>",
  "confidence": <0.0-1.0>,
  "reason": "<one-sentence explanation>"
}

Definitions:
- bad_retrieval:  The context does not contain information needed to answer the question.
- hallucination:  The answer makes claims not supported by the context.
- prompt_issue:   The context contained the answer but the LLM misinterpreted or ignored it.
"""


def analyze_failure(record: dict) -> str:
    """
    Classify a single incorrect feedback record.

    Args:
        record: A feedback record from the FeedbackCollector.

    Returns:
        Failure type string: 'bad_retrieval' | 'hallucination' | 'prompt_issue'.
    """
    settings = get_settings()
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.0,
        max_tokens=256,
    )

    chunks_text = "\n".join(
        f"  [{c.get('reference', '?')}] {c.get('source', '')} p{c.get('page', '?')}"
        for c in record.get("context_chunks", [])
    )

    user_msg = (
        f"Question: {record['question']}\n\n"
        f"Retrieved context sources:\n{chunks_text or 'None'}\n\n"
        f"Generated answer (marked incorrect):\n{record['answer']}"
    )

    messages = [("system", _SYSTEM_PROMPT), ("human", user_msg)]

    try:
        response = llm.invoke(messages)
        raw = re.sub(r"```(?:json)?", "", response.content.strip()).strip().strip("`")
        data = json.loads(raw)
        failure_type = data.get("failure_type", "unknown")
        logger.info(f"[FailureAnalyzer] id={record['id']} → {failure_type} ({data.get('confidence', '?')})")
        return failure_type
    except Exception as exc:
        logger.warning(f"[FailureAnalyzer] Analysis failed ({exc})")
        return "unknown"


def run_batch_analysis() -> dict[str, int]:
    """
    Analyze all unclassified incorrect records and update the feedback DB.

    Returns:
        Dict with counts per failure_type.
    """
    db = _load_db()
    counts: dict[str, int] = {}
    updated = False

    for record in db:
        if not record.get("is_correct", True) and record.get("failure_type") is None:
            failure_type = analyze_failure(record)
            record["failure_type"] = failure_type
            counts[failure_type] = counts.get(failure_type, 0) + 1
            updated = True

    if updated:
        _save_db(db)
        logger.info(f"[FailureAnalyzer] Batch analysis complete: {counts}")

    return counts
