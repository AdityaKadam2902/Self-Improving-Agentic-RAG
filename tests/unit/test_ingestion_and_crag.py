"""
Unit tests for Phase 3: Layout-Aware Ingestion and Corrective RAG (CRAG).

Verifies:
1. Hierarchical Layout-Aware Document Loader (Markdown, CSV, Table formatting).
2. Contextual Chunk Enrichment (Document summary synthesis, structural breadcrumbs).
3. Persistent Incremental BM25 Inverted Index (Sub-millisecond query latency, incremental updates, serialization, tenant filtering).
4. Corrective RAG (CRAG) Quality Evaluator (CORRECT, AMBIGUOUS, INCORRECT classification, noise stripping).
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.ingestion.document_loader import (
    RawDocument,
    format_table_as_markdown,
    load_document,
)
from backend.ingestion.text_splitter import (
    TextChunk,
    synthesize_document_summary,
    split_documents,
)
from backend.ingestion.cached_bm25 import (
    PersistentBM25Index,
    get_bm25_index,
)
from backend.agents.retriever import RetrievedChunk
from backend.agents.crag_evaluator import (
    CRAGQualityEvaluator,
    score_chunk_relevance,
    strip_noise_sentences,
)


def test_format_table_as_markdown():
    rows = [
        ["Product", "Q1 Revenue", "Q2 Revenue"],
        ["Cloud Platform", "$120M", "$150M"],
        ["AI Agents", "$45M", "$90M"],
    ]
    md = format_table_as_markdown(rows)
    assert "| Product | Q1 Revenue | Q2 Revenue |" in md
    assert "| --- | --- | --- |" in md
    assert "| Cloud Platform | $120M | $150M |" in md
    assert "| AI Agents | $45M | $90M |" in md


def test_document_loader_csv():
    csv_bytes = b"id,service,sla_uptime,latency_target\n1,Auth0,99.99%,50ms\n2,VectorDB,99.95%,20ms\n"
    docs = load_document(csv_bytes, "infrastructure.csv")

    assert len(docs) == 1
    doc = docs[0]
    assert doc.metadata["has_tables"] is True
    assert doc.metadata["file_type"] == "csv"
    assert doc.metadata["row_count"] == 2
    assert "| id | service | sla_uptime | latency_target |" in doc.content
    assert "| 1 | Auth0 | 99.99% | 50ms |" in doc.content


def test_document_loader_markdown():
    md_bytes = b"""# Platform Architecture
The platform is designed for enterprise autonomous RAG with zero trust.

## Security Subsystem
The security subsystem implements indirect prompt injection defenses.
| Threat Vector | Mitigation Strategy | Severity |
|---|---|---|
| Delimiter breakout | Regex boundary clamp | High |
| Role usurpation | Deterministic scrubber | Critical |

## Ingestion Pipeline
Layout-aware parsing preserves tabular documents.
"""
    docs = load_document(md_bytes, "architecture.md")
    assert len(docs) == 3

    # Section 1
    assert docs[0].metadata["section_title"] == "Platform Architecture"
    assert "Platform Architecture" in docs[0].metadata["section_hierarchy"]
    assert docs[0].metadata["has_tables"] is False

    # Section 2 (Has table)
    assert docs[1].metadata["section_title"] == "Security Subsystem"
    assert docs[1].metadata["has_tables"] is True
    assert docs[1].metadata["table_count"] >= 1
    assert "| Threat Vector | Mitigation Strategy | Severity |" in docs[1].content

    # Section 3
    assert docs[2].metadata["section_title"] == "Ingestion Pipeline"
    assert docs[2].metadata["has_tables"] is False


def test_contextual_chunk_enrichment():
    raw_docs = [
        RawDocument(
            content="Apollo Financial Overview for Fiscal Year 2025. Total gross merchandise value rose by 38% globally.",
            metadata={
                "source": "apollo_fy25.pdf",
                "page": 1,
                "section_title": "Executive Summary",
                "section_hierarchy": ["Annual Report", "Executive Summary"],
                "has_tables": False,
            },
        ),
        RawDocument(
            content="Operating margin increased to 28.5% driven by serverless infrastructure cost optimizations.",
            metadata={
                "source": "apollo_fy25.pdf",
                "page": 2,
                "section_title": "Financial Highlights",
                "section_hierarchy": ["Annual Report", "Financial Highlights"],
                "has_tables": False,
            },
        ),
    ]

    summary = synthesize_document_summary(raw_docs)
    assert "Apollo Financial Overview" in summary or "merchandise value" in summary

    chunks = split_documents(raw_docs, chunk_size=200, chunk_overlap=30, enrich_context=True)
    assert len(chunks) == 2

    # Check structural contextual breadcrumb in enriched content
    first_chunk = chunks[0]
    assert "[Document: apollo_fy25.pdf | Section: Annual Report > Executive Summary" in first_chunk.content
    assert first_chunk.raw_content.startswith("Apollo Financial Overview")
    assert first_chunk.metadata["document_summary"] == summary
    assert first_chunk.metadata["section_title"] == "Executive Summary"


def test_persistent_bm25_inverted_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "bm25_test.pkl")
        bm25 = PersistentBM25Index(persist_path=index_path)

        documents = [
            ("chunk_1", "Autonomous agent orchestration uses LangGraph state machines.", {"source": "orchestration.md", "tenant_id": "corp_a"}),
            ("chunk_2", "Zero trust security shields against indirect prompt injections and PII leaks.", {"source": "security.md", "tenant_id": "corp_a"}),
            ("chunk_3", "Semantic query caching delivers sub-40ms latency with cosine similarity matching.", {"source": "cache.md", "tenant_id": "corp_b"}),
            ("chunk_4", "Corrective RAG filters distractor noise and evaluates chunk relevance before generation.", {"source": "crag.md", "tenant_id": "corp_a"}),
        ]

        added = bm25.add_documents(documents, persist=True)
        assert added == 4
        assert bm25.total_docs == 4
        assert os.path.exists(index_path)

        # 1. Benchmark query execution speed (Exit Gate: < 15ms)
        t0 = time.perf_counter()
        results = bm25.query("prompt injection security defenses", top_k=2)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert len(results) > 0
        top_cid, top_text, top_meta, top_score = results[0]
        assert top_cid == "chunk_2"
        assert top_score > 0.0
        assert elapsed_ms < 15.0, f"BM25 latency exceeded SLA: {elapsed_ms:.2f}ms"

        # 2. Test Tenant Isolation Filtering
        results_corp_b = bm25.query("caching latency", top_k=5, tenant_filter={"tenant_id": "corp_b"})
        assert len(results_corp_b) == 1
        assert results_corp_b[0][0] == "chunk_3"

        results_corp_a_only = bm25.query("caching latency", top_k=5, tenant_filter={"tenant_id": "corp_a"})
        assert len(results_corp_a_only) == 0

        # 3. Test Incremental Addition
        new_doc = [("chunk_5", "Cross encoder reranking sorts chunks by relevance logits.", {"source": "rerank.md", "tenant_id": "corp_a"})]
        bm25.add_documents(new_doc, persist=True)
        assert bm25.total_docs == 5
        rerank_hits = bm25.query("cross encoder relevance", top_k=1)
        assert rerank_hits[0][0] == "chunk_5"

        # 4. Test Source Removal
        removed = bm25.remove_source("security.md", persist=True)
        assert removed == 1
        assert bm25.total_docs == 4
        post_del_hits = bm25.query("prompt injection", top_k=5)
        assert not any(cid == "chunk_2" for cid, *_ in post_del_hits)

        # 5. Test Disk Serialization Reload
        reloaded_bm25 = PersistentBM25Index(persist_path=index_path)
        assert reloaded_bm25.total_docs == 4
        cached_hits = reloaded_bm25.query("LangGraph state machines", top_k=1)
        assert cached_hits[0][0] == "chunk_1"


def test_crag_evaluator_filtering():
    evaluator = CRAGQualityEvaluator(correct_threshold=0.60, ambiguous_threshold=0.30)
    query = "What is the operating margin and revenue growth of Apollo in 2025?"

    chunk_correct = RetrievedChunk(
        chunk_id="c_correct",
        content="In fiscal year 2025, Apollo achieved an operating margin of 28.5% with revenue growth of 38% globally.",
        metadata={"source": "apollo.pdf"},
        vector_score=0.88,
    )

    chunk_ambiguous = RetrievedChunk(
        chunk_id="c_ambig",
        content="Apollo expanded operations into European markets during 2025. Standard disclaimers and cookie policies apply to all web traffic.",
        metadata={"source": "apollo.pdf"},
        vector_score=0.45,
    )

    chunk_distractor = RetrievedChunk(
        chunk_id="c_noise",
        content="Cooking recipes for holiday pumpkin pies require brown sugar, cinnamon, and nutmeg.",
        metadata={"source": "recipes.txt"},
        vector_score=0.05,
    )

    # 1. Test Single Chunk Scoring
    eval_corr = score_chunk_relevance(query, chunk_correct, correct_thresh=0.60, ambiguous_thresh=0.30)
    assert eval_corr.status == "CORRECT"
    assert eval_corr.confidence_score >= 0.60

    eval_ambig = score_chunk_relevance(query, chunk_ambiguous, correct_thresh=0.60, ambiguous_thresh=0.30)
    assert eval_ambig.status == "AMBIGUOUS"

    eval_noise = score_chunk_relevance(query, chunk_distractor, correct_thresh=0.60, ambiguous_thresh=0.30)
    assert eval_noise.status == "INCORRECT"
    assert eval_noise.confidence_score < 0.30

    # 2. Test Collective Evaluation & Noise Filtering
    crag_res = evaluator.evaluate(query, [chunk_correct, chunk_ambiguous, chunk_distractor])
    assert crag_res.action == "CORRECT"
    assert len(crag_res.kept_chunks) == 2  # Correct and cleaned Ambiguous kept
    assert len(crag_res.discarded_chunks) == 1  # Distractor stripped
    assert crag_res.discarded_chunks[0].chunk_id == "c_noise"

    # 3. Test All Distractors Scenario
    all_distractors = [
        chunk_distractor,
        RetrievedChunk(chunk_id="c_noise2", content="Bicycle gear maintenance instructions.", metadata={}),
    ]
    crag_fail_res = evaluator.evaluate(query, all_distractors)
    assert crag_fail_res.action == "INCORRECT"
    assert len(crag_fail_res.kept_chunks) == 0
    assert len(crag_fail_res.discarded_chunks) == 2


def test_strip_noise_sentences():
    text = (
        "Apollo recorded operating margins of 28.5%. "
        "Terms and conditions are subject to change without notice. "
        "Total revenue reached 1.2 billion dollars."
    )
    cleaned, stripped = strip_noise_sentences(text, ["operating", "margin", "revenue"])
    assert stripped is True
    assert "Terms and conditions are subject to change" not in cleaned
    assert "operating margins of 28.5%" in cleaned
    assert "1.2 billion dollars" in cleaned


if __name__ == "__main__":
    print("Running Phase 3 unit tests...")
    test_format_table_as_markdown()
    print("PASS: test_format_table_as_markdown")

    test_document_loader_csv()
    print("PASS: test_document_loader_csv")

    test_document_loader_markdown()
    print("PASS: test_document_loader_markdown")

    test_contextual_chunk_enrichment()
    print("PASS: test_contextual_chunk_enrichment")

    test_persistent_bm25_inverted_index()
    print("PASS: test_persistent_bm25_inverted_index")

    test_crag_evaluator_filtering()
    print("PASS: test_crag_evaluator_filtering")

    test_strip_noise_sentences()
    print("PASS: test_strip_noise_sentences")

    print("\nALL PHASE 3 TESTS COMPLETED AND PASSED!")
