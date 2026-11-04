"""
Unit tests for Phase 4: Atomic Claim-Level NLI Verification Engine.

Verifies:
1. Propositional Claim Decomposer (atomic claim splitting, compound sentence decomposition, numeric fact detection).
2. Natural Language Inference (NLI) Entailment Evaluator (ENTAILED, CONTRADICTED, UNVERIFIABLE, GroundingScore calculation).
3. Token-Span Citation Attribution and Hallucination Redactor.
4. End-to-end integration via verify_answer.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.agents.context_builder import BuiltContext
from backend.agents.answer_verifier import verify_answer, VerificationResult
from backend.verification.claim_extractor import extract_atomic_claims
from backend.verification.entailment_verifier import (
    EntailmentVerifier,
    evaluate_single_claim,
)
from backend.verification.citation_mapper import map_citations


def test_claim_extractor_decomposition():
    text = (
        "Apollo recorded an operating margin of 28.5%, while revenue grew by 38% globally. "
        "The company expanded its autonomous logistics network across Europe."
    )
    result = extract_atomic_claims(text)
    assert len(result.claims) == 3
    assert result.sentence_count == 2

    c1 = result.claims[0]
    assert "operating margin of 28.5%" in c1.text
    assert c1.contains_numeric_fact is True
    assert "Apollo" in c1.entities

    c2 = result.claims[1]
    assert "revenue grew by 38%" in c2.text
    assert c2.contains_numeric_fact is True

    c3 = result.claims[2]
    assert "autonomous logistics" in c3.text
    assert "Europe" in c3.entities


def test_entailment_verifier_grounded_answer():
    context = BuiltContext(
        context_text=(
            "Apollo Annual Report FY25:\n"
            "Operating margins expanded to 28.5% driven by operational efficiencies.\n"
            "Total gross revenue increased by 38% year-over-year."
        ),
        citations=[
            {
                "chunk_id": "chunk_apollo_01",
                "source": "apollo_fy25.pdf",
                "page": 1,
                "quote": "Operating margins expanded to 28.5% driven by operational efficiencies. Total gross revenue increased by 38% year-over-year.",
            }
        ],
        chunk_ids=["chunk_apollo_01"],
    )

    answer = "Apollo achieved an operating margin of 28.5% and revenue increased by 38%."
    verifier = EntailmentVerifier(grounding_threshold=0.70)
    nli_res = verifier.verify("What were Apollo's financial results?", answer, context)

    assert nli_res.is_grounded is True
    assert nli_res.verdict == "grounded"
    assert nli_res.grounding_score >= 0.70
    assert nli_res.entailed_count >= 1
    assert nli_res.unverifiable_count == 0


def test_entailment_verifier_hallucination_detection():
    context = BuiltContext(
        context_text="Apollo operates cloud services and recorded modest 5% growth in North America.",
        citations=[
            {
                "chunk_id": "chunk_cloud_02",
                "source": "services.md",
                "page": 2,
                "quote": "Apollo operates cloud services and recorded modest 5% growth in North America.",
            }
        ],
        chunk_ids=["chunk_cloud_02"],
    )

    # Completely hallucinated claim with fabricated numbers
    answer = "Apollo acquired Quantum Dynamics for 450 billion dollars in cash and stock."
    verifier = EntailmentVerifier(grounding_threshold=0.70)
    nli_res = verifier.verify("Did Apollo make any acquisitions?", answer, context)

    assert nli_res.is_grounded is False
    assert nli_res.verdict == "hallucination"
    assert nli_res.grounding_score < 0.50
    assert nli_res.unverifiable_count >= 1


def test_citation_mapper_and_redaction():
    context = BuiltContext(
        context_text="Serverless latency averages 42 milliseconds under high concurrency.",
        citations=[
            {
                "chunk_id": "chunk_infra_03",
                "source": "benchmark.txt",
                "page": 4,
                "quote": "Serverless latency averages 42 milliseconds under high concurrency.",
            }
        ],
        chunk_ids=["chunk_infra_03"],
    )

    answer = (
        "Serverless latency averages 42 milliseconds under high concurrency. "
        "The system was founded on Mars in the year 1840."
    )

    verifier = EntailmentVerifier(grounding_threshold=0.70)
    nli_res = verifier.verify("What is serverless latency?", answer, context)
    assert nli_res.total_claims == 2

    # Map citations without redaction
    attr_res = map_citations(answer, nli_res, context, redact_unverified=False)
    assert len(attr_res.citations) == 1
    assert attr_res.citations[0].source == "benchmark.txt"
    assert attr_res.citations[0].page == 4

    # Map citations with redaction enabled
    attr_redacted = map_citations(answer, nli_res, context, redact_unverified=True)
    assert "Serverless latency averages 42 milliseconds" in attr_redacted.attributed_text
    assert "Mars in the year 1840" not in attr_redacted.attributed_text
    assert attr_redacted.redacted_claims_count == 1


def test_verify_answer_agent_integration():
    context = BuiltContext(
        context_text="The security shield prevents indirect prompt injections by scanning delimiters.",
        citations=[
            {
                "chunk_id": "chunk_sec_01",
                "source": "security_guide.pdf",
                "page": 3,
                "quote": "The security shield prevents indirect prompt injections by scanning delimiters.",
            }
        ],
        chunk_ids=["chunk_sec_01"],
    )

    answer = "The security shield prevents indirect prompt injections by scanning delimiters."
    v_result: VerificationResult = verify_answer("How does the security shield work?", answer, context)

    assert v_result.is_grounded is True
    assert v_result.verdict == "grounded"
    assert v_result.grounding_score >= 0.80
    assert v_result.total_claims >= 1
    assert v_result.entailed_claims >= 1
    assert len(v_result.attributed_citations) >= 1
    assert v_result.attributed_citations[0]["source"] == "security_guide.pdf"


if __name__ == "__main__":
    print("Running Phase 4 unit tests...")
    test_claim_extractor_decomposition()
    print("PASS: test_claim_extractor_decomposition")

    test_entailment_verifier_grounded_answer()
    print("PASS: test_entailment_verifier_grounded_answer")

    test_entailment_verifier_hallucination_detection()
    print("PASS: test_entailment_verifier_hallucination_detection")

    test_citation_mapper_and_redaction()
    print("PASS: test_citation_mapper_and_redaction")

    test_verify_answer_agent_integration()
    print("PASS: test_verify_answer_agent_integration")

    print("\nALL PHASE 4 TESTS COMPLETED AND PASSED!")
