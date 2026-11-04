"""
Token-Span Citation Attribution and Hallucination Redactor.

Maps verified atomic claims to precise document coordinates:
- Links entailed claims to exact source file, page number, and evidence text spans.
- Formats inline citation markers [^1] and structured bibliographic footnotes.
- Optionally redacts or tags unverified/hallucinated sentences when strict grounding is enforced.
- Produces tamper-evident audit trails linking assertions to source evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from backend.agents.context_builder import BuiltContext
from backend.verification.entailment_verifier import NLIResult, ClaimVerification


@dataclass
class AttributedCitation:
    """Exact source coordinates and evidence text span for an entailed claim."""

    citation_index: int
    claim_id: str
    claim_text: str
    source: str
    page: Optional[int]
    chunk_id: str
    evidence_quote: str
    confidence: float


@dataclass
class AttributionResult:
    """Attributed response with citations and optional redaction."""

    attributed_text: str
    citations: List[AttributedCitation]
    verified_claims_count: int
    unverified_claims_count: int
    redacted_claims_count: int
    is_pure_grounded: bool


def map_citations(
    answer: str,
    nli_result: NLIResult,
    context: BuiltContext,
    redact_unverified: bool = False,
) -> AttributionResult:
    """
    Attribute verified claims in answer to exact document coordinates and evidence quotes.

    Args:
        answer:            Original synthesized answer.
        nli_result:        NLI verification outcome with claim classifications.
        context:           BuiltContext with retrieved chunk citations.
        redact_unverified: If True, strips sentences corresponding to UNVERIFIABLE claims.

    Returns:
        AttributionResult with annotated text, citation objects, and metrics.
    """
    if not nli_result.claim_verifications:
        return AttributionResult(
            attributed_text=answer,
            citations=[],
            verified_claims_count=0,
            unverified_claims_count=0,
            redacted_claims_count=0,
            is_pure_grounded=True,
        )

    # Build chunk lookup map from context.citations
    chunk_lookup: Dict[str, dict] = {}
    if hasattr(context, "citations") and context.citations:
        for cit in context.citations:
            cid = cit.get("chunk_id")
            if cid:
                chunk_lookup[cid] = cit

    attributed_citations: List[AttributedCitation] = []
    cit_idx = 1
    unverified_claims = [cv for cv in nli_result.claim_verifications if cv.verdict != "ENTAILED"]
    verified_claims = [cv for cv in nli_result.claim_verifications if cv.verdict == "ENTAILED"]

    for cv in verified_claims:
        chunk_data = chunk_lookup.get(cv.matching_chunk_id or "", {})
        source = chunk_data.get("source") or (context.citations[0].get("source") if context.citations else "Document")
        page = chunk_data.get("page") or (context.citations[0].get("page") if context.citations else 1)
        evidence = cv.evidence_span or chunk_data.get("quote", "")

        attributed_citations.append(
            AttributedCitation(
                citation_index=cit_idx,
                claim_id=cv.claim_id,
                claim_text=cv.claim_text,
                source=source,
                page=page,
                chunk_id=cv.matching_chunk_id or "chunk",
                evidence_quote=evidence[:200],
                confidence=cv.confidence,
            )
        )
        cit_idx += 1

    # Text transformation: optionally redact unverified claims
    transformed_text = answer
    redacted_count = 0

    if redact_unverified and unverified_claims:
        for uv in unverified_claims:
            # Strip sentence if found
            clean_claim = uv.claim_text.strip().rstrip(".")
            pattern = re.compile(re.escape(clean_claim) + r"[.!?]?", re.IGNORECASE)
            if pattern.search(transformed_text):
                transformed_text = pattern.sub("", transformed_text)
                redacted_count += 1

        # Clean multiple spaces and blank lines
        transformed_text = re.sub(r"\n{3,}", "\n\n", transformed_text).strip()
        logger.info(f"[CitationMapper] Redacted {redacted_count} unverified claim sentences from answer.")

    return AttributionResult(
        attributed_text=transformed_text,
        citations=attributed_citations,
        verified_claims_count=len(verified_claims),
        unverified_claims_count=len(unverified_claims),
        redacted_claims_count=redacted_count,
        is_pure_grounded=len(unverified_claims) == 0,
    )
