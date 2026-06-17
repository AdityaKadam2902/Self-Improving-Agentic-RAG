# RAG Workspace

> A document Q&A application with a FastAPI backend, a React frontend, hybrid retrieval, reranking, answer verification, and a feedback loop that improves retrieval over time.

---

## Overview

This project is a practical **agentic RAG system** built for document search and question answering. The backend is responsible for ingestion, retrieval, verification, and feedback tracking. The frontend provides the chat interface, document upload flow, and result traceability.

When a user marks an answer as incorrect, the system classifies the failure and updates future retrieval using keyword boosts and prompt improvements.

---

## Architecture

```
User
 │
 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│         (Chat UI · Document Upload · Feedback · Traces)         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI API Gateway                          │
│         /api/chat · /api/upload · /api/feedback · /api/improve │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RAG Orchestrator (LangGraph)                 │
│                                                                 │
│  ┌────────────┐   ┌────────────┐   ┌──────────────────────┐   │
│  │  Query     │ → │  Query     │ → │   Hybrid Retrieval   │   │
│  │  Understand│   │  Rewriter  │   │  (Vector + BM25 RRF) │   │
│  └────────────┘   └────────────┘   └──────────┬───────────┘   │
│                                               │                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Reranker (cross-encoder) → Context Builder              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                               │                 │
│  ┌────────────────┐   ┌───────────────────────┴──────────┐    │
│  │ Answer Verifier│ ← │       Answer Generator            │    │
│  │ (hallucination │   │  (Groq Llama 3.3 70B + memory)   │    │
│  │  detection)    │   └──────────────────────────────────┘    │
│  └────────┬───────┘                                            │
│           │ (if hallucination & retries < 2 → regenerate)      │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│          Self-Improvement Engine      │
│  ┌─────────────────┐                 │
│  │ Feedback        │                 │
│  │ Collector       │                 │
│  └────────┬────────┘                 │
│           │                          │
│  ┌────────▼────────┐                 │
│  │ Failure         │                 │
│  │ Analyzer        │  bad_retrieval  │
│  │ (LLM-powered)   │  hallucination  │
│  └────────┬────────┘  prompt_issue   │
│           │                          │
│  ┌────────▼─────────────────────┐   │
│  │ Retrieval + Prompt Optimizer │   │
│  │  keyword boosts · new prompts│   │
│  └──────────────────────────────┘   │
└───────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│               ChromaDB (Persistent Vector Store)                │
│                   + BM25 Index (in-memory)                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

| Agent | Role |
|---|---|
| **Query Understanding** | Detects intent, extracts keywords, classifies query type |
| **Query Rewriter** | Rewrites the query for better retrieval; injects learned keywords |
| **Hybrid Retriever** | Combines dense (ChromaDB cosine) + sparse (BM25) search via Reciprocal Rank Fusion |
| **Reranker** | Scores all candidates with a cross-encoder; selects top 3 |
| **Context Builder** | Formats chunks into a labelled context block with source citations |
| **Answer Generator** | Generates a grounded answer with Groq Llama 3.3 70B |
| **Answer Verifier** | Checks answer faithfulness; triggers regeneration if hallucination detected |

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq API (Llama 3.3 70B Versatile) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Agent Orchestration | LangGraph |
| LLM Framework | LangChain + LangChain-Groq |
| Vector Database | ChromaDB (persistent) |
| Keyword Search | BM25 (rank-bm25) |
| Backend | FastAPI + Uvicorn |
| Frontend | React + React Scripts |
| Evaluation | RAGAS |
| Observability | Loguru |
| Document Parsing | PyMuPDF, python-docx |

---

## Project Structure

```
self_improving_agentic_rag/
├── backend/
│   ├── main.py                    # FastAPI app factory
│   ├── config.py                  # Settings from env vars
│   ├── orchestrator.py            # LangGraph pipeline
│   ├── api/
│   │   ├── upload.py              # Document upload & listing
│   │   └── chat.py                # Chat, feedback, improve endpoints
│   ├── agents/
│   │   ├── query_understanding.py
│   │   ├── query_rewriter.py
│   │   ├── retriever.py           # Hybrid retrieval + RRF
│   │   ├── reranker.py            # Cross-encoder reranking
│   │   ├── context_builder.py
│   │   ├── answer_generator.py
│   │   └── answer_verifier.py
│   ├── ingestion/
│   │   ├── document_loader.py     # PDF / DOCX / TXT parser
│   │   ├── text_splitter.py       # Tiktoken-aware chunking
│   │   └── embedding_generator.py # Embed + store in ChromaDB
│   ├── improvement/
│   │   ├── feedback_collector.py  # Persist user feedback
│   │   ├── failure_analyzer.py    # Classify failure type
│   │   └── retrieval_optimizer.py # Keyword + prompt optimization
│   └── memory/
│       └── conversation_memory.py # Rolling session history
├── frontend/
│   ├── package.json               # React Scripts entry points
│   ├── public/
│   │   └── index.html             # Browser shell
│   └── src/
│       ├── App.js                 # Main UI shell
│       ├── api.js                 # Frontend API client
│       ├── index.js               # React bootstrap
│       ├── index.css              # Global styling
│       └── components/            # Chat, sidebar, input, and states
├── evaluation/
│   └── rag_evaluator.py           # RAGAS-based evaluation
├── vector_db/                     # ChromaDB persistence (git-ignored)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.11+
- A [Groq API key](https://console.groq.com) (free tier available)

### 1. Clone and Install

```bash
git clone <repo-url>
cd self_improving_agentic_rag

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and set GROQ_API_KEY=your_key_here
```

### 3. Start the Backend

```bash
uvicorn backend.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

### 4. Start the Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm start
```

Open: http://localhost:3000

Keep both the backend and frontend terminals running. The frontend uses the local proxy configured in [frontend/package.json](frontend/package.json) to talk to the backend at `http://localhost:8000`.

---

## Usage

### 1. Upload Documents

Use the sidebar to upload PDF, DOCX, or TXT files. The system will parse, chunk, embed, and index them automatically.

### 2. Ask Questions

Type questions in the chat input. Each answer includes:
- The generated answer with inline `[Source N]` citations
- Source metadata (filename, page number, relevance score)
- A pipeline trace (rewritten query, verification verdict, latency, tokens)

### 3. Provide Feedback

After each answer, click **👍 Correct** or **👎 Incorrect**. Incorrect answers are logged for analysis.

### 4. Run Self-Improvement

Click **🔧 Run Optimization Cycle** in the sidebar to:
1. Classify stored failures (bad retrieval / hallucination / prompt issue)
2. Generate keyword expansions for retrieval failures
3. Generate an improved system prompt for prompt failures

Future queries will automatically benefit from these improvements.

---

## Development Notes

- The frontend is intentionally small and direct. A few inline styles remain because they made iteration easier during development.
- The session ID shown in the UI is only for the active browser session; it is not a login or account identifier.
- The backend and frontend can be run separately, which makes it easier to debug one side without touching the other.
- The project is set up for local development first, with the backend and frontend running as separate services.

---

## Known Gaps

- Some of the UI still uses component-level styles. That is acceptable for now, but I would probably move repeated pieces into shared styles later.
- The feedback and improvement flow is intentionally lightweight. It is useful for demos and experiments, but it is not a complete production workflow yet.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload and index a document |
| `GET` | `/api/documents` | List all indexed documents |
| `DELETE` | `/api/documents/{source}` | Remove a document |
| `POST` | `/api/chat` | Ask a question |
| `POST` | `/api/feedback` | Record answer feedback |
| `POST` | `/api/improve` | Trigger self-improvement cycle |
| `DELETE` | `/api/session/{id}` | Clear session memory |
| `GET` | `/health` | Health check |

---

## Evaluation

Run evaluation on accumulated feedback:

```bash
python -m evaluation.rag_evaluator \
    --feedback ./vector_db/feedback.json \
    --output ./evaluation/report.json
```

### Metrics

| Metric | Description |
|---|---|
| `faithfulness` | Fraction of answer claims supported by context |
| `answer_relevancy` | Degree to which the answer addresses the question |
| `context_recall` | Coverage of ground truth in retrieved context |
| `context_precision` | Signal-to-noise of retrieved context |
| `user_feedback_accuracy` | Percentage of answers marked correct by users |

---

## Self-Improvement Flow

```
User marks answer incorrect
         │
         ▼
FeedbackCollector stores:
  question · answer · context · timestamp
         │
         ▼
FailureAnalyzer classifies:
  bad_retrieval  → context didn't contain the answer
  hallucination  → LLM invented facts
  prompt_issue   → context had the answer but LLM misused it
         │
         ▼
RetrievalOptimizer:
  bad_retrieval  → LLM generates synonym/expansion keywords
                   stored and injected into future queries
  prompt_issue   → LLM generates improved system prompt
                   loaded by AnswerGenerator on next query
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | required | Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model name |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `RERANKER_MODEL` | `ms-marco-MiniLM-L-6-v2` | Cross-encoder model |
| `CHUNK_SIZE` | `800` | Max tokens per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap tokens between chunks |
| `TOP_K_RETRIEVAL` | `10` | Candidates per hybrid search |
| `TOP_K_RERANK` | `3` | Final context chunks after reranking |
| `CONVERSATION_HISTORY_LIMIT` | `5` | Message pairs kept in memory |

---

## Future Improvements

- **Multi-modal support**: PDF images, tables, diagrams via vision LLM
- **Streaming responses**: SSE / WebSocket for real-time token streaming
- **Redis-backed memory**: Persistent conversation history across restarts
- **Multi-collection routing**: Route queries to relevant document collections
- **Active learning**: Auto-trigger optimization after N failures
- **RAGAS continuous evaluation**: Nightly automated regression testing
- **Metadata filtering**: Filter retrieval by document, date, or custom tags
- **Role-based access**: Per-user document namespaces

---

## Notes For Reviewers

- The repository is intentionally split into a Python backend and a React frontend.
- The frontend talks to the backend through the local proxy defined in [frontend/package.json](frontend/package.json).
- If you run this on a fresh machine, install Python dependencies first, then install frontend dependencies, then start both services separately.

---

## License

MIT
