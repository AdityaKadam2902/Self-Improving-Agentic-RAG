"""
Atomic Claim-Level Verification & NLI Package.
"""

from backend.verification.claim_extractor import (
    AtomicClaim,
    ClaimExtractionResult,
    extract_atomic_claims,
)
from backend.verification.entailment_verifier import (
    ClaimVerification,
    NLIResult,
    EntailmentVerifier,
    get_entailment_verifier,
)
from backend.verification.citation_mapper import (
    AttributedCitation,
    AttributionResult,
    map_citations,
)

__all__ = [
    "AtomicClaim",
    "ClaimExtractionResult",
    "extract_atomic_claims",
    "ClaimVerification",
    "NLIResult",
    "EntailmentVerifier",
    "get_entailment_verifier",
    "AttributedCitation",
    "AttributionResult",
    "map_citations",
]
