"""
Propositional Claim Decomposer.

Deconstructs complex synthesized answers into atomic, self-contained factual claims:
- Parses paragraphs, lists, and compound statements into discrete propositions.
- Detects numeric facts (percentages, currency, quantities, dates).
- Isolates key entities and predicate assertions for granular NLI verification.
- Deterministic pure-Python execution running in <1ms without token costs.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class AtomicClaim:
    """A single atomic, verifiable factual proposition."""

    claim_id: str
    text: str
    sentence_index: int
    contains_numeric_fact: bool = False
    entities: List[str] = field(default_factory=list)


@dataclass
class ClaimExtractionResult:
    """Result of propositional claim decomposition."""

    claims: List[AtomicClaim]
    original_text: str
    sentence_count: int
    extraction_ms: float


_NUMERIC_PATTERN = re.compile(
    r"(\$?\b\d+([.,]\d+)?\s*(%|percent|billion|million|thousand|k|m|b|usd|eur|gbp)?\b|\b\d{4}\b)",
    re.IGNORECASE,
)

_CONJUNCTION_SPLIT_PATTERN = re.compile(
    r",?\s+(?:and|while|whereas|as well as|furthermore|additionally|moreover)\s+",
    re.IGNORECASE,
)


def _extract_entities(text: str) -> List[str]:
    """Extract capitalized entity candidates and acronyms."""
    # Find sequences of capitalized words or capitalized acronyms
    words = re.findall(r"\b[A-Z][A-Za-z0-9_-]+\b", text)
    stopwords = {"The", "A", "An", "In", "On", "At", "For", "With", "By", "From", "It", "This", "That", "These", "Those"}
    return [w for w in words if w not in stopwords]


def extract_atomic_claims(text: str) -> ClaimExtractionResult:
    """
    Deconstruct an answer string into a sequence of atomic factual claims.

    Args:
        text: The synthesized text to deconstruct.

    Returns:
        ClaimExtractionResult with list of AtomicClaim instances.
    """
    t0 = time.perf_counter()
    clean_text = text.strip()
    if not clean_text:
        return ClaimExtractionResult(
            claims=[],
            original_text="",
            sentence_count=0,
            extraction_ms=0.0,
        )

    # 1. Break into structural lines and sentences
    raw_lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    sentence_units: List[str] = []

    for line in raw_lines:
        # Strip bullet points and list numbering
        clean_line = re.sub(r"^(\*|-|\d+\.)\s+", "", line).strip()
        if not clean_line or clean_line.startswith("|"):
            continue  # skip markdown table borders

        # Split into sentences using sentence boundary heuristics
        sents = re.split(r"(?<=[.!?])\s+", clean_line)
        for s in sents:
            s_clean = s.strip()
            if len(s_clean) > 8:
                sentence_units.append(s_clean)

    claims: List[AtomicClaim] = []
    claim_counter = 1

    for sent_idx, sentence in enumerate(sentence_units):
        # 2. Decompose compound clauses if both clauses contain substantive factual content
        clauses = _CONJUNCTION_SPLIT_PATTERN.split(sentence)

        valid_clauses = [c.strip().strip(",") for c in clauses if len(c.strip()) > 15]

        if len(valid_clauses) > 1 and all(len(c.split()) >= 4 for c in valid_clauses):
            # Compound sentence successfully split into atomic propositions
            for clause in valid_clauses:
                # Ensure clause ends with punctuation for grammatical completeness
                formatted_clause = clause if clause.endswith((".", "!", "?")) else clause + "."
                has_num = bool(_NUMERIC_PATTERN.search(formatted_clause))
                ents = _extract_entities(formatted_clause)

                claims.append(
                    AtomicClaim(
                        claim_id=f"claim_{claim_counter:03d}",
                        text=formatted_clause,
                        sentence_index=sent_idx,
                        contains_numeric_fact=has_num,
                        entities=ents,
                    )
                )
                claim_counter += 1
        else:
            # Atomic sentence
            has_num = bool(_NUMERIC_PATTERN.search(sentence))
            ents = _extract_entities(sentence)

            claims.append(
                AtomicClaim(
                    claim_id=f"claim_{claim_counter:03d}",
                    text=sentence,
                    sentence_index=sent_idx,
                    contains_numeric_fact=has_num,
                    entities=ents,
                )
            )
            claim_counter += 1

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.debug(
        f"[ClaimExtractor] Decomposed {len(sentence_units)} sentences into "
        f"{len(claims)} atomic claims in {elapsed_ms}ms"
    )

    return ClaimExtractionResult(
        claims=claims,
        original_text=clean_text,
        sentence_count=len(sentence_units),
        extraction_ms=elapsed_ms,
    )
