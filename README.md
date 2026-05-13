# LiveOS Brain

A personal knowledge graph and multi-hop question-answering system. Notes — including text, audio, images, PDFs, and other documents — are automatically extracted into a structured knowledge graph. A conversational interface then answers questions over the graph using an iterative retrieval loop that traverses entity relationships across multiple notes.

---

## Table of Contents

1. [What It Is](#what-it-is)
2. [Architecture](#architecture)
3. [Ingestion Pipeline](#ingestion-pipeline)
4. [Retrieval Pipeline](#retrieval-pipeline)
5. [Infrastructure](#infrastructure)
6. [Frontend](#frontend)
7. [LLM & Model Support](#llm--model-support)
8. [Benchmark Results](#benchmark-results)
9. [Local Setup](#local-setup)
10. [Local Model Setup](#local-model-setup)
11. [Environment Variables](#environment-variables)
12. [Running the Stack](#running-the-stack)

---

## What It Is

LiveOS Brain is a personal AI knowledge base. You write notes — plain text, voice recordings, images, PDFs, Word documents, spreadsheets — and the system:

1. **Extracts** entities, relationships, and concepts from the note using an LLM
2. **Deduplicates** entities across notes using node IDs and name normalisation
3. **Builds** a property graph where entities are nodes and LLM-extracted predicates are edges
4. **Detects communities** of related entities using the Leiden algorithm
5. **Indexes** everything into a vector store (Qdrant), a full-text search engine (Typesense), and a graph database (Kuzu)
6. **Answers questions** conversationally via an iterative retrieval loop that walks the graph, accumulates findings across hops, and synthesises a final answer

The system is designed to run entirely locally. All LLM inference, embedding, and reranking can run on local hardware via Ollama or LM Studio. Cloud LLM providers (Gemini, OpenAI, Anthropic, HuggingFace) are also supported and switchable via environment variables.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Next.js Frontend                        │
│   Notes editor · Chat interface · 2D/3D graph visualisation     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (REST, /api/v1/*)
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI Backend (uvicorn)                     │
│                                                                 │
│  ┌─────────────────┐   ┌──────────────────┐                    │
│  │ Ingestion        │   │ Chat / Retrieval  │                    │
│  │ Workflow         │   │ Workflow          │                    │
│  │ (LangGraph)      │   │ (iterative loop)  │                    │
│  └────────┬─────────┘   └──────────┬───────┘                   │
│           │                        │                            │
│  ┌────────▼────────────────────────▼───────┐                   │
│  │              Service Layer               │                   │
│  │  LLM · Embedding · Reranker · Graph      │                   │
│  │  Qdrant · Typesense · Multimedia         │                   │
│  └────────┬────────────────────────┬───────┘                   │
└───────────┼────────────────────────┼───────────────────────────┘
            │                        │
┌───────────▼──────┐   ┌─────────────▼──────────────────────────┐
│  Kuzu (embedded) │   │  Docker-managed services                │
│  graph database  │   │  Qdrant · Typesense · PostgreSQL · MinIO│
└──────────────────┘   └────────────────────────────────────────┘
```

### Key design decisions

| Decision | Choice | Reason |
|---|---|---|
| Graph database | Kuzu (embedded) | Replaces Neo4j — no container, no Cypher syntax constraints on dynamic edge types |
| Full-text search | Typesense | Replaces Elasticsearch — lighter, BM25 + exact match, much simpler to operate |
| Vector store | Qdrant | Three collections: `node_cores`, `node_relationships`, `node_isolated_contexts` |
| Relational DB | PostgreSQL | Stores raw notes with processing status; asyncpg for async access |
| Object store | MinIO | Stores uploaded files (audio, images, PDFs) — R2-compatible API |
| Embedding | `qwen3-embedding:0.6b` (local) | 1024-dim; requires Qwen3 instruction prefix for queries |
| Reranker | `qwen3-reranker-0.6b` (local) | Cross-encoder; filters top-10 candidates before LLM context window |
| LLM | Configurable | Ollama, LM Studio, Gemini, OpenAI, Anthropic, or HuggingFace |

---

## Ingestion Pipeline

When a note is saved, the backend triggers a LangGraph workflow:

```
Note saved
    │
    ▼
[1] Multimedia node
    ├── Audio (.webm/.m4a/.mp3/.wav) → Whisper large-v3-turbo transcription
    ├── Images → Florence-2-large captioning + OCR
    ├── PDF → pdfplumber text extraction
    └── Word/Excel → python-docx / openpyxl extraction
    │
    ▼
[2] LLM extraction (single call)
    ├── Entities (name, type, description)
    ├── Relationships (subject → predicate → object, confidence, strength)
    ├── Concepts (abstract ideas from the note)
    └── Note title (folded into same call — no second round-trip)
    │
    ▼
[3] Graph write (Kuzu)
    ├── Upsert entity nodes by normalised name + type
    ├── Write SEMANTIC_REL edges with full provenance
    ├── Predicate cleaning (strip entity name tokens from rel types)
    └── Link note node → entity nodes via REFERENCES edges
    │
    ▼
[4] Vector indexing (Qdrant)
    ├── node_cores: entity summary embeddings
    ├── node_relationships: NL relationship sentence embeddings
    └── node_isolated_contexts: per-entity context embeddings
    │
    ▼
[5] Full-text indexing (Typesense)
    └── node name, type, isolated contexts, relationship NL text
    │
    ▼
[6] Community detection (Leiden, batched)
    └── Recomputed in background after each ingestion batch
```

**Extraction stats from benchmark runs (990 HotPotQA notes):**

| Metric | Value |
|---|---|
| Avg entities extracted per note | 9.22 |
| Total entity nodes (post-dedup) | 7,284 |
| Deduplication rate | 20.2% (9,129 instances → 7,284 unique) |
| Total relationships written | 8,238 |
| Unique predicate types | 3,168 |
| Predicates auto-cleaned | 607 |
| Community nodes (Leiden) | 1,362 |
| Avg ingestion time per note (local LLM) | 49.71 s (Gemma3:4b via Ollama) |
| Avg ingestion time per note (cloud LLM) | 34.02 s (Gemini Flash Lite) |

---

## Retrieval Pipeline

Chat queries go through a multi-iteration research loop, not a single vector lookup:

```
User query
    │
    ▼
[1] ITERATIVE LOOP (up to 10 iterations, configurable)
    │
    ├── Hybrid search
    │   ├── Vector search (Qdrant — cosine similarity, threshold 0.45 pre-rerank)
    │   ├── BM25 full-text search (Typesense — keyword + phrase match)
    │   └── Entity name exact match
    │
    ├── node_id deduplication (replaces prior name-based dedup)
    │
    ├── Graph neighbour expansion
    │   ├── 1-hop Kuzu graph traversal from top candidates
    │   └── Qdrant NL relationship lookup for neighbour context
    │
    ├── Reranking (qwen3-reranker-0.6b, top-10)
    │
    └── LLM step
        ├── Extract FINDING from accumulated context, or
        └── Emit NEXT_QUERY for next iteration
    │
    ▼
[2] Loop exits when can_answer = True or iteration limit reached
    └── Returns best FINDING + top-6 scored context docs
    │
    ▼
[3] Response with inline note citations
```

The loop accumulates findings across iterations. On exhaustion (no `can_answer=True`), the last non-empty FINDING is returned without an additional synthesis call.

---

## Infrastructure

All services except Kuzu (which is embedded) run as Docker containers:

```sh
docker compose up -d
```

| Service | Image | Port | Purpose |
|---|---|---|---|
| Typesense | `typesense/typesense:27.1` | 8108 | Full-text search (BM25) |
| PostgreSQL | `postgres:latest` | 5433 | Notes + processing status |
| MinIO | `minio/minio:latest` | 9000 / 9001 | File storage (S3-compatible) |
| Qdrant | `qdrant/qdrant:latest` | 6333 / 6334 | Vector search |

Kuzu is embedded — no container needed. The database files live at `data/kuzu/kuzu_graph`.

---

## Frontend

Built with Next.js 15 (App Router) and Tailwind CSS. Three main views:

| Route | Purpose |
|---|---|
| `/` | Landing page with navigation |
| `/notes` | Notes editor — create, edit, search, filter by ingestion status; supports file attachments and voice recording |
| `/chat` | Conversational interface — markdown rendering, file previews, thumbs up/down feedback, source citations |
| `/graph` | 2D force-directed graph visualisation of the knowledge graph |
| `/graph-3d` | 3D graph visualisation |

The notes editor supports:
- Plain text with Markdown preview
- File attachments (images, audio, PDF, Word, Excel)
- In-browser voice recording (WebM → backend Whisper transcription)
- Per-note ingestion status filter (all / ingested / ingesting / saved / failed)
- Auto-save on edit

---

## LLM & Model Support

The LLM provider is set via `LLM_PROVIDER` in `backend/.env`. The same config file controls the ingestion model, chat model, embedding model, and reranker.

**Supported providers:**

| Provider | `LLM_PROVIDER` value | Notes |
|---|---|---|
| Ollama | `ollama` | Default. Runs locally at `http://127.0.0.1:11434` |
| LM Studio | `lm_studio` | Local OpenAI-compatible server |
| OpenAI | `openai` | Requires `OPENAI_API_KEY` |
| Google Gemini | `gemini` | Requires `GEMINI_API_KEY` |
| Anthropic | `anthropic` | Requires `ANTHROPIC_API_KEY` |
| HuggingFace | `huggingface` | Requires `HUGGINGFACE_API_KEY` |

A separate `INGESTION_LLM_MODEL` can be set to use a different (usually smaller) model for extraction vs. chat — for example, `gemma3:4b` for ingestion and `gemma4:latest` for chat.

An optional `LLM_FALLBACK_PROVIDER` kicks in if the primary provider fails.

---

## Benchmark Results

All benchmarks use the [HotPotQA](https://hotpotqa.github.io/) multi-hop QA dataset (100 questions, 990-note knowledge graph). HotPotQA requires bridging facts from two or more documents to answer correctly — it is a strong stress test for multi-hop retrieval.

### Final Implementation — Model Comparison

Knowledge graph: 9,636 nodes / 8,238 relationships — ingested with `gemma3:4b` (local, Ollama). Infrastructure identical across all three runs; only the chat LLM varies.

| Metric | Gemini 3.1 Flash Lite | Gemma3:4b (local) | Gemma4:e4b (local) |
|---|---|---|---|
| **Inference** | Google Cloud API | Ollama local | Ollama local |
| **Exact Match (EM)** | **59.0%** | 30.0% | 58.0% |
| **Fuzzy Match** | 76.0% | 41.0% | **81.0%** |
| **Token F1** | 0.705 | 0.383 | **0.737** |
| **Contains expected** | 67.0% | 36.0% | **74.0%** |
| **Hard failures** | 24 | 59 | **19** |
| **Avg response time** | **18.10 s** | 91.66 s | 212.10 s |
| **Retrieval Recall** | 0.665 | 0.625 | **0.715** |
| **Retrieval Precision** | **0.330** | **0.351** | 0.349 |
| **Retrieval F1** | 0.441 | 0.449 | **0.469** |
| **Full-recall questions** | 42 | 37 | **52** |
| **EM at full recall** | 62% | 24% | 50% |
| **Wall clock (100 Qs)** | ~30 min | ~2.5 h | ~8.75 h |
| **Error count** | 0 | 0 | 0 |

**Key takeaways:**

- **The LLM is the dominant variable.** The 29 pp EM spread (30% → 59%) is entirely attributable to reasoning quality — retrieval precision across all three runs is nearly identical (0.330–0.351).
- **Gemma4:e4b matches cloud accuracy locally.** At 58% EM vs. 59% for Gemini Flash Lite and 81% fuzzy match (best of any run), a sufficiently large local model can match cloud API quality. The cost is 212 s mean latency.
- **Gemini Flash Lite is the interactive production choice.** 18.10 s mean, 59% EM, 76% fuzzy — 4.4× faster than Gemma3:4b with nearly double the accuracy.
- **Gemma3:4b under-performs on reasoning, not retrieval.** Its retrieval precision (0.351) is the highest of the three — but EM at full-recall is only 24%, versus 62% for Flash Lite. The model retrieves correctly and then fails to reason over what it retrieved.

### Historical Architecture Progression

| Approach | Graph DB | Search | LLM | EM | Avg response |
|---|---|---|---|---|---|
| Sub Questions (Feb 2026) | Neo4j | Elasticsearch | Gemini 3 Flash Preview | 62% | 50.5 s |
| Joint Approach (Mar 2026) | Neo4j | Elasticsearch | Gemini Flash Lite | 61% | ~43 s |
| Final Implementation (May 2026) | **Kuzu** | **Typesense** | Gemini Flash Lite | **59%** | **18.10 s** |
| Final Implementation (May 2026) | **Kuzu** | **Typesense** | Gemma4:e4b (local) | **58%** | 212.10 s |

The move from Neo4j + Elasticsearch to Kuzu + Typesense cut response time from ~43 s to 18.10 s (2.4×) while maintaining near-identical accuracy, and eliminated all external graph database and search service dependencies.

---

## Local Setup

### Prerequisites

- Docker Desktop (for Qdrant, Typesense, PostgreSQL, MinIO)
- Python 3.11+
- Node.js 20+
- Ollama (for local LLM/embedding inference)

### 1. Clone and install

```sh
git clone https://github.com/josetseph/LiveOS.git
cd LiveOS
```

### 2. Start infrastructure services

```sh
docker compose up -d
```

### 3. Backend

```sh
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the example env and fill in your values:

```sh
cp .env.example .env
```

Run database migrations:

```sh
alembic upgrade head
```

Initialise Qdrant collections and Typesense schema:

```sh
python scripts/init_qdrant.py
python scripts/init_typesense.py
```

Start the API server:

```sh
uvicorn app.main:app --reload --port 8000
```

### 4. Frontend

```sh
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Local Model Setup

Three models must be downloaded manually and placed in `backend/models/` before starting the backend. These run locally — no cloud API needed for multimedia processing or reranking.

### Required models

| Directory | Hugging Face source | Purpose |
|---|---|---|
| `backend/models/florence-2-large/` | [`microsoft/Florence-2-large`](https://huggingface.co/microsoft/Florence-2-large) | Vision — image captioning and OCR |
| `backend/models/whisper-large-v3-turbo/` | [`openai/whisper-large-v3-turbo`](https://huggingface.co/openai/whisper-large-v3-turbo) | Audio — speech-to-text transcription |
| `backend/models/qwen3-reranker-0.6b/` | [`Qwen/Qwen3-Reranker-0.6B`](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Retrieval — reranking search results |

### Download instructions

```sh
pip install huggingface_hub

huggingface-cli download microsoft/Florence-2-large \
  --local-dir backend/models/florence-2-large

huggingface-cli download openai/whisper-large-v3-turbo \
  --local-dir backend/models/whisper-large-v3-turbo

huggingface-cli download Qwen/Qwen3-Reranker-0.6B \
  --local-dir backend/models/qwen3-reranker-0.6b
```

> **Note:** Florence-2-large requires `trust_remote_code=True` and includes custom modeling code. Do not rename or restructure the downloaded files.

The backend reads models from the path configured by `MODELS_PATH` in `backend/app/core/config.py`, which defaults to `models` relative to the backend root.

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

```sh
# LLM Provider — "ollama" | "lm_studio" | "openai" | "gemini" | "anthropic" | "huggingface"
LLM_PROVIDER=ollama
LLM_MODEL=gemma4:latest
INGESTION_LLM_MODEL=gemma3:4b

# Embedding — "ollama" | "lm_studio" | "auto"
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=qwen3-embedding:0.6b

# Cloud providers (only needed if using cloud LLMs)
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Web fallback search (optional)
TAVILY_API_KEY=

# Retrieval tuning
RERANKER_ENABLED=true
RERANKER_TOP_K=10
MAX_LOOP_ITERATIONS=10
VECTOR_SIMILARITY_THRESHOLD=0.50
VECTOR_PRE_RERANK_THRESHOLD=0.45

# Benchmark mode (set true only when testing against external datasets)
BENCHMARK_MODE=false
```

Full reference: [`backend/app/core/config.py`](backend/app/core/config.py)

---

## Running the Stack

### Reset everything (start fresh)

```sh
cd backend
source venv/bin/activate
python scripts/reset_all.py
```

Individual reset scripts exist for each store: `reset_qdrant.py`, `reset_typesense.py`, `reset_kuzu.py`, `reset_postgres.py`, `reset_minio.py`, `reset_ingestion.py`.

### Benchmark evaluation

```sh
cd backend
source venv/bin/activate
python tests/benchmark/evaluate.py
```

Results are written to `Results/` as JSON + Markdown reports.
