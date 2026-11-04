"""
Security module providing indirect prompt injection defense, PII scrubbing, and RBAC.
"""

from backend.security.injection_shield import (
    scan_for_injection,
    sanitize_context_delimiters,
    InjectionCheckResult,
)
from backend.security.pii_scrubber import (
    scrub_pii,
    PIIScrubResult,
)
from backend.security.tenant_manager import (
    UserContext,
    build_vector_tenant_filter,
    validate_chunk_access,
)

__all__ = [
    "scan_for_injection",
    "sanitize_context_delimiters",
    "InjectionCheckResult",
    "scrub_pii",
    "PIIScrubResult",
    "UserContext",
    "build_vector_tenant_filter",
    "validate_chunk_access",
]
