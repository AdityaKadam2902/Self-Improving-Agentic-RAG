# Documentation Architecture Index
## Autonomous Enterprise-Grade Self-Optimizing RAG Platform

This repository divides technical specifications, implementation roadmaps, security guardrails, evaluation benchmarks, and operational tracking into modular, version-controlled documents.

---

## Documentation Suite Index

| Document | Primary Focus | Key Audience |
|---|---|---|
| [ARCHITECTURE.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/ARCHITECTURE.md) | System C4 model, subsystem specifications, LangGraph state machine, data contracts, and component interfaces | Principal Architects, Staff AI Engineers |
| [IMPLEMENTATION_STEPS.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/IMPLEMENTATION_STEPS.md) | Granular step-by-step development phases, task assignments, test criteria, and exit gates | Core Developers, Implementers |
| [PROJECT_STATUS.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/PROJECT_STATUS.md) | Live component readiness matrix, benchmark targets vs. baselines, technical debt tracker | Engineering Managers, Technical Leads |
| [SECURITY_SPEC.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/SECURITY_SPEC.md) | Adversarial threat modeling, indirect prompt injection defense, vector-level RBAC, and PII scrubbing | Security Architects, Compliance Teams |
| [EVALUATION_FRAMEWORK.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/EVALUATION_FRAMEWORK.md) | RAG Triad metrics (Faithfulness, Recall, Precision), golden dataset specs, and automated regression gates | MLOps Engineers, Eval Specialists |
| [COST_AND_INFERENCE_SPEC.md](file:///d:/Git-Hub-Personal/Self-Improving-Agentic-RAG/docs/COST_AND_INFERENCE_SPEC.md) | Inference unit economics, semantic query caching (<40ms), token budget caps, and model cascading SLAs | FinOps, Product Owners |

---

## Execution Strategy

The platform is engineered across 7 systematic phases:
1. **Phase 1: Foundation Hardening, Concurrency & Security Core** (Async event loop, SQLite WAL, Indirect Prompt Injection Shield, PII scrubbing).
2. **Phase 2: Economic Routing & Semantic Query Cache** (Semantic Vector Cache, SLA & Token Budget Controller, Adaptive Intent Router).
3. **Phase 3: Context-Enriched Ingestion & Corrective RAG (CRAG)** (Hierarchical table-aware loader, contextual chunk enrichment, persistent cached BM25, CRAG relevance gate).
4. **Phase 4: Atomic Claim-Level Verification & NLI Attribution** (Propositional claim decomposition, NLI entailment scoring, token-span citation mapping).
5. **Phase 5: Evolutionary Self-Improvement & Automated Regression Testing** (Failure pattern clustering, golden dataset benchmark suite, automated regression gate with rollback).
6. **Phase 6: Enterprise UI & Interactive Pipeline Glassbox** (Tailwind design system, code syntax highlighting, glassbox timeline visualizer, real-time metrics dashboard).
7. **Phase 7: DevOps, Production Packaging & Observability** (Docker Compose stack, OpenTelemetry tracing, Prometheus `/metrics`, GitHub Actions CI/CD).
