"""
Atomic Claim-Level Answer Verification Agent.

Checks whether a generated answer is grounded in the retrieved context using
fine-grained Propositional NLI:
- Decomposes the response into atomic factual claims.
- Evaluates entailment against retrieved context chunks.
- Computes an aggregate GroundingScore and maps precise token-span citations.
- Triggers orchestrator regeneration if hallucinated or ungrounded claims are detected.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Dict, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field

from backend.agents.context_builder import BuiltContext
from backend.config import get_settings
from backend.verification.entailment_verifier import get_entailment_verifier, NLIResult
from backend.verification.citation_mapper import map_citations


class VerificationResult(BaseModel):
    is_grounded: bool = Field(description="True if the answer is supported by the context.")
    confidence: float = Field(description="0.0-1.0 confidence that the answer is grounded.")
    verdict: str = Field(description="One of: grounded | hallucination | insufficient_context")
    explanation: str = Field(description="Brief explanation of the verdict.")
    grounding_score: float = Field(default=1.0, description="Ratio of verified atomic claims to total claims.")
    total_claims: int = Field(default=0, description="Number of atomic factual claims evaluated.")
    entailed_claims: int = Field(default=0, description="Number of strictly entailed claims.")
    unverified_claims: int = Field(default=0, description="Number of unverified or hallucinated claims.")
    claim_details: List[dict] = Field(default_factory=list, description="Claim-level breakdown.")
    attributed_citations: List[dict] = Field(default_factory=list, description="Attributed evidence coordinates.")


def verify_answer(
    query: str,
    answer: str,
    context: BuiltContext,
) -> VerificationResult:
    """
    Verify whether *answer* is grounded in *context* using atomic claim NLI evaluation.

    Args:
        query:   The user question.
        answer:  The generated answer to verify.
        context: The BuiltContext used to generate the answer.

    Returns:
        VerificationResult with granular grounding metrics and claim evaluations.
    """
    # 1. Execute fine-grained Propositional NLI evaluation
    verifier = get_entailment_verifier()
    nli_res: NLIResult = verifier.verify(query=query, answer=answer, context=context)

    # 2. Map claims to exact token-span citations
    attr_res = map_citations(answer=answer, nli_result=nli_res, context=context)

    claim_breakdowns = [
        {
            "claim_id": cv.claim_id,
            "claim_text": cv.claim_text,
            "verdict": cv.verdict,
            "confidence": cv.confidence,
            "matching_chunk_id": cv.matching_chunk_id,
            "evidence_span": cv.evidence_span,
            "reason": cv.reason,
        }
        for cv in nli_res.claim_verifications
    ]

    citation_payloads = [
        {
            "citation_index": c.citation_index,
            "claim_id": c.claim_id,
            "claim_text": c.claim_text,
            "source": c.source,
            "page": c.page,
            "chunk_id": c.chunk_id,
            "evidence_quote": c.evidence_quote,
            "confidence": c.confidence,
        }
        for c in attr_res.citations
    ]

    # 3. Optional LLM verification pass if API key is active and verdict is ambiguous
    settings = get_settings()
    if settings.groq_api_key and nli_res.total_claims > 0 and nli_res.verdict == "insufficient_context":
        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                temperature=0.0,
                max_tokens=256,
            )
            prompt = (
                f"Determine if the answer is grounded in the context.\n"
                f"Context: {context.context_text[:2000]}\n"
                f"Answer: {answer}\n"
                f"Respond with JSON: {{\"is_grounded\": bool, \"verdict\": \"grounded\"|\"hallucination\"|\"insufficient_context\", \"confidence\": float, \"explanation\": str}}"
            )
            resp = llm.invoke([("human", prompt)])
            raw = re.sub(r"```(?:json)?", "", resp.content).strip().strip("`")
            llm_data = json.loads(raw)

            if not llm_data.get("is_grounded", True):
                nli_res.is_grounded = False
                nli_res.verdict = "hallucination"
                nli_res.explanation = llm_data.get("explanation", nli_res.explanation)
        except Exception as e:
            logger.debug(f"[AnswerVerifier] LLM secondary verification pass skipped: {e}")

    logger.info(
        f"[AnswerVerifier] verdict={nli_res.verdict} score={nli_res.grounding_score:.2f} "
        f"({nli_res.entailed_count}/{nli_res.total_claims} entailed)"
    )

    return VerificationResult(
        is_grounded=nli_res.is_grounded,
        confidence=nli_res.grounding_score,
        verdict=nli_res.verdict,
        explanation=nli_res.explanation,
        grounding_score=nli_res.grounding_score,
        total_claims=nli_res.total_claims,
        entailed_claims=nli_res.entailed_count,
        unverified_claims=nli_res.unverifiable_count,
        claim_details=claim_breakdowns,
        attributed_citations=citation_payloads,
    )
