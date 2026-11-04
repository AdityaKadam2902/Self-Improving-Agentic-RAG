"""
High-Performance PII and Secret Redactor.

Deterministic regex engine for identifying and masking sensitive personal identifiers
and cryptographic credentials before vector indexing and logging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("pii_scrubber")


@dataclass
class PIIScrubResult:
    redacted_text: str
    redactions_count: int
    categories_found: List[str] = field(default_factory=list)


# Compiled pattern table for sensitive credentials and identifiers
_PII_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # 1. Cryptographic Private Keys
    (
        re.compile(r"-----BEGIN [A-Z\s]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z\s]+ PRIVATE KEY-----"),
        "<REDACTED_PRIVATE_KEY>",
        "PRIVATE_KEY",
    ),
    # 2. JSON Web Tokens (JWT)
    (
        re.compile(r"\beyJ[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\b"),
        "<REDACTED_JWT_TOKEN>",
        "JWT_TOKEN",
    ),
    # 3. Known API Keys (OpenAI, GitHub, Groq)
    (
        re.compile(r"\b(?:sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{36}|gsk_[a-zA-Z0-9_-]{20,})\b"),
        "<REDACTED_API_KEY>",
        "API_KEY",
    ),
    # 4. Social Security Numbers (SSN)
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "<REDACTED_SSN>",
        "SSN",
    ),
    # 5. Credit Card Numbers
    (
        re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        "<REDACTED_CREDIT_CARD>",
        "CREDIT_CARD",
    ),
    # 6. Email Addresses (Optional masking for strict GDPR / privacy mode)
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "<REDACTED_EMAIL>",
        "EMAIL_ADDRESS",
    ),
]


def scrub_pii(text: str, mask_emails: bool = False) -> PIIScrubResult:
    """
    Scan and scrub sensitive PII and cryptographic credentials from text.
    """
    if not text:
        return PIIScrubResult(redacted_text=text, redactions_count=0)

    categories: List[str] = []
    count = 0
    scrubbed = text

    for pattern, replacement, category in _PII_PATTERNS:
        if category == "EMAIL_ADDRESS" and not mask_emails:
            continue

        matches = pattern.findall(scrubbed)
        if matches:
            count += len(matches)
            categories.append(category)
            scrubbed = pattern.sub(replacement, scrubbed)

    if count > 0:
        logger.info(f"[PIIScrubber] Redacted {count} sensitive item(s): {list(set(categories))}")

    return PIIScrubResult(
        redacted_text=scrubbed,
        redactions_count=count,
        categories_found=list(set(categories)),
    )
