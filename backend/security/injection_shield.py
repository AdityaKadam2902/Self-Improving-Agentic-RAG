"""
Indirect Prompt Injection Scanner and Adversarial Shield.

Detects and neutralizes prompt-override sequences, jailbreaks, and delimiter
injection attacks in user queries and uploaded document contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("injection_shield")

from backend.storage.db import _log_security_incident_sync


@dataclass
class InjectionCheckResult:
    is_suspicious: bool
    confidence: float
    matched_patterns: List[str] = field(default_factory=list)
    sanitized_text: str = ""


# Compiled heuristic signatures for adversarial jailbreak & instruction hijack attempts
_INJECTION_SIGNATURES: List[Tuple[re.Pattern, str, float]] = [
    (
        re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"),
        "IGNORE_PREVIOUS_INSTRUCTIONS",
        0.95,
    ),
    (
        re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:prior|above|previous)\s+(?:rules|directives|constraints|instructions)\b"),
        "DISREGARD_RULES",
        0.95,
    ),
    (
        re.compile(r"(?i)\bsystem\s+prompt\s+override\b"),
        "SYSTEM_PROMPT_OVERRIDE",
        0.90,
    ),
    (
        re.compile(r"(?i)\byou\s+are\s+now\s+(?:in\s+)?developer\s+mode\b"),
        "DEVELOPER_MODE_JAILBREAK",
        0.95,
    ),
    (
        re.compile(r"(?i)\breveal\s+(?:your\s+)?(?:secret\s+)?(?:system\s+)?(?:prompt|instructions|keys)\b"),
        "EXFILTRATE_SYSTEM_PROMPT",
        0.85,
    ),
    (
        re.compile(r"(?i)<\s*(?:system|assistant|im_start|im_end|s)\s*>"),
        "RESERVED_ROLE_DELIMITER",
        0.90,
    ),
    (
        re.compile(r"\[/?(?:INST|SYS)\]"),
        "LLAMA_CONTROL_TOKEN",
        0.95,
    ),
]


def scan_for_injection(text: str, tenant_id: str = "default") -> InjectionCheckResult:
    """
    Scan input text for adversarial injection signatures and command overrides.
    Returns structured diagnosis and sanitized text string.
    """
    if not text:
        return InjectionCheckResult(is_suspicious=False, confidence=0.0, sanitized_text=text)

    matched: List[str] = []
    max_confidence: float = 0.0
    sanitized = text

    for pattern, name, conf in _INJECTION_SIGNATURES:
        if pattern.search(sanitized):
            matched.append(name)
            max_confidence = max(max_confidence, conf)
            # Neutralize the offending token pattern by replacing with benign indicator
            sanitized = pattern.sub(f"[FILTERED_DIRECTIVE_{name}]", sanitized)

    is_suspicious = len(matched) > 0

    if is_suspicious:
        logger.warning(f"[InjectionShield] Adversarial pattern detected: {matched} (Confidence: {max_confidence:.2f})")
        try:
            _log_security_incident_sync(
                incident_type="INDIRECT_PROMPT_INJECTION",
                offending_payload=text,
                action_taken=f"Sanitized: {matched}",
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.error(f"[InjectionShield] Failed to log incident: {exc}")

    return InjectionCheckResult(
        is_suspicious=is_suspicious,
        confidence=max_confidence,
        matched_patterns=matched,
        sanitized_text=sanitized,
    )


def sanitize_context_delimiters(text: str) -> str:
    """
    Escape XML and format delimiters to prevent boundary breakouts when
    document text is framed within XML context tags.
    """
    if not text:
        return ""
    # Neutralize XML tag escapes
    escaped = text.replace("<document_context>", "&lt;document_context&gt;")
    escaped = escaped.replace("</document_context>", "&lt;/document_context&gt;")
    escaped = escaped.replace("<chunk", "&lt;chunk")
    escaped = escaped.replace("</chunk>", "&lt;/chunk&gt;")
    return escaped
