# LiveOS

A knowledge graph and multi-hop question-answering system. Notes — including text, audio, images, PDFs, and other documents — are automatically extracted into a structured knowledge graph. A conversational interface then answers questions over the graph using an iterative retrieval loop that traverses entity relationships across multiple notes.

---

## Table of Contents

1. [What It Is](#what-it-is)
2. [Screenshots](#screenshots)
3. [Architecture](#architecture)
4. [Ingestion Pipeline](#ingestion-pipeline)
5. [Retrieval Pipeline](#retrieval-pipeline)
6. [Infrastructure](#infrastructure)
7. [Frontend](#frontend)
8. [LLM & Model Support](#llm--model-support)
9. [Runtime Model Switching](#runtime-model-switching)
10. [Benchmark Results](#benchmark-results)
11. [Local Setup](#local-setup)
12. [Docker Deployment](#docker-deployment)
13. [Local Model Setup](#local-model-setup)
14. [Environment Variables](#environment-variables)
15. [Running the Stack](#running-the-stack)
16. [Knowledge Bases](#knowledge-bases)

---

## What It Is

LiveOS is an AI-powered knowledge base. You write notes — plain text, voice recordings, images, PDFs, Word documents, spreadsheets — and the system:

1. **Extracts** entities, relationships, and concepts from the note using an LLM
2. **Deduplicates** entities across notes using node IDs and name normalisation
3. **Builds** a property graph where entities are nodes and LLM-extracted predicates are edges
4. **Detects communities** of related entities using the Leiden algorithm
5. **Indexes** everything into a vector store (Qdrant), a full-text search engine (Typesense), and a graph database (Kuzu)
6. **Answers questions** conversationally via an iterative retrieval loop that walks the graph, accumulates findings across hops, and synthesises a final answer
7. **Highlights** entity mentions live in notes and chat — every entity name found in ingested content is automatically underlined; clicking any mention opens an inline detail panel without leaving the page
8. **Isolates knowledge** into multiple named knowledge bases — each with its own graph, vector store, and full-text index

The system is designed to run entirely locally. All LLM inference, embedding, and reranking can run on local hardware via Ollama or LM Studio. Cloud LLM providers (Gemini, OpenAI, Anthropic, HuggingFace) are also supported and switchable via environment variables.

---

## Screenshots

![Home](Platform%20Images/home_view.png)

<table>
  <tr>
    <td><img src="Platform%20Images/chat_view.png" alt="Chat interface"/></td>
    <td><img src="Platform%20Images/notes_page_edit_view.png" alt="Notes editor"/></td>
  </tr>
  <tr>
    <td align="center"><em>Chat interface</em></td>
    <td align="center"><em>Notes editor</em></td>
  </tr>
</table>

![3D Knowledge Graph](Platform%20Images/graph_view.png)

<table>
  <tr>
    <td><img src="Platform%20Images/graph_view_node_centered.png" alt="Node-centred graph view"/></td>
    <td><img src="Platform%20Images/graph_node_view.png" alt="Node detail panel"/></td>
  </tr>
  <tr>
    <td align="center"><em>Node-centred view</em></td>
    <td align="center"><em>Node detail panel</em></td>
  </tr>
</table>

<table>
  <tr>
    <td><img src="Platform%20Images/knowledge_base_selector_view.png" alt="Knowledge base manager"/></td>
    <td><img src="Platform%20Images/llm_model_settings_view.png" alt="Runtime model settings"/></td>
  </tr>
  <tr>
    <td align="center"><em>Knowledge base manager</em></td>
    <td align="center"><em>Runtime model settings</em></td>
  </tr>
</table>

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Next.js Frontend                        │
│     Notes editor · Chat interface · 3D graph visualisation      │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (REST, /api/v1/*)
┌────────────────────────────▼────────────────────────────────────┐
│                    FastAPI Backend (uvicorn)                    │
│                                                                 │
│          ┌─────────────────┐   ┌──────────────────┐             │
│          │ Ingestion       │   │ Chat / Retrieval │             │
│          │ Workflow        │   │ Workflow         │             │
│          │ (LangGraph)     │   │ (iterative loop) │             │
│          └────────┬────────┘   └──────────┬───────┘             │
│                   │                       │                     │
│          ┌────────▼───────────────────────▼───────┐             │
│          │              Service Layer             │             │
│          │  LLM · Embedding · Reranker · Graph    │             │
│          │  Qdrant · Typesense · Multimedia       │             │
│          └────────┬────────────────────────┬──────┘             │
└───────────────────┼────────────────────────┼────────────────────┘
                    │                        │
┌───────────────────▼──────┐   ┌─────────────▼────────────────────┐
│      Kuzu (embedded)     │   │      Docker-managed services     │
│      graph database      │   │      Qdrant · Typesense          │
│                          │   │      PostgreSQL · RustFS         │
└──────────────────────────┘   └──────────────────────────────────┘
```

### Key design decisions

| Decision | Choice | Reason |
|---|---|---|
| Graph database | Kuzu (embedded) | Replaces Neo4j — no container, no Cypher syntax constraints on dynamic edge types |
| Full-text search | Typesense | Replaces Elasticsearch — lighter, BM25 + exact match, much simpler to operate |
| Vector store | Qdrant | Three collections: `node_cores`, `node_relationships`, `node_isolated_contexts` |
| Relational DB | PostgreSQL | Stores raw notes with processing status; asyncpg for async access |
| Object store | RustFS | S3-compatible, Apache 2.0; stores uploaded files (audio, images, PDFs) |
| Embedding | `qwen3-embedding:0.6b` (local) | 1024-dim; requires Qwen3 instruction prefix for queries |
| Reranker | `qwen3-reranker-0.6b` (local) | Cross-encoder; filters top-10 candidates before LLM context window |
| LLM | Configurable | Ollama, LM Studio, Gemini, OpenAI, Anthropic, or HuggingFace |
| Multi-KB | `KBRegistry` (JSON-persisted) | Each KB has its own Kuzu graph, Qdrant collections, and Typesense collection; notes are isolated per KB in Postgres |

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
    ├── PDF → PyMuPDF text extraction
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
    └── Model thinking exposed in collapsible dropdown (when available)
```

The loop accumulates findings across iterations. On exhaustion (no `can_answer=True`), the last non-empty FINDING is returned without an additional synthesis call.

If the active LLM exposes reasoning (e.g. `reasoning_content` from LM Studio, or `<think>` tags from models like Gemma4), the thinking is passed through to the frontend and shown in a collapsible "Model thinking" section above the answer.

---

## Infrastructure

All services except Kuzu (which is embedded) run as Docker containers:

```sh
docker compose up -d
```

| Service | Image | Port | Purpose |
|---|---|---|---|
| PostgreSQL | `postgres:latest` | 15432 | Notes + processing status |
| RustFS | `rustfs/rustfs:latest` | 9000 / 9001 | File storage (S3-compatible) |
| Qdrant | `qdrant/qdrant:latest` | 6333 / 6334 | Vector search |
| Typesense | `typesense/typesense:27.1` | 8108 | Full-text search (BM25) |
| Backend | built from `./backend` | 8700 | FastAPI API server |
| Frontend | built from `./frontend` | 3700 | Next.js UI |

Kuzu is embedded — no container needed. The database files live at `data/kuzu/kuzu_graph`.

---

## Frontend

Built with Next.js 16 (App Router) and Tailwind CSS.

| Route | Purpose |
|---|---|
| `/` | Landing page with navigation |
| `/notes` | Notes editor — create, edit, search, filter by ingestion status; supports file attachments and voice recording |
| `/chat` | Conversational interface — markdown rendering, file previews, thumbs up/down feedback, source citations |
| `/graph-3d` | 3D graph visualisation |
| `/kb` | Knowledge base manager — create, rename, switch, and delete knowledge bases |
| `/settings` | Runtime LLM settings — switch provider, chat model, ingestion model, and server URL without restarting |

The notes editor supports:
- Plain text with Markdown preview
- **Entity mention highlighting** — after ingestion, known entity names are scanned in the note at load time and highlighted as clickable badges in both edit and preview modes; no special markup is stored in the note
- **Entity autocomplete** — typing a capitalised word surfaces matching entities from the knowledge graph as inline suggestions
- **Entity detail panel** — clicking any highlighted entity name slides in a panel showing the entity's type, description, relationships, and isolated contexts, with a link to its node in the 3D graph
- File attachments (images, audio, PDF, Word, Excel)
- In-browser voice recording — audio is transcoded to AAC/M4A server-side on upload, ensuring playback works across all browsers including Safari
- Per-note ingestion status filter (all / ingested / ingesting / saved / failed)
- Auto-save on edit
- Note content segmentation — image, PDF, and audio sections are visually separated with labelled dividers in preview mode

The chat interface supports:
- Multi-hop answers with inline source citations
- **Entity highlighting in AI responses** — entity names mentioned in answers are scanned and rendered as clickable badges; the same entity detail panel slides in on click
- Collapsible model thinking display (for models that expose reasoning tokens)
- Note preview modal with segmented content display and entity highlighting

---

## LLM & Model Support

The LLM provider is set via `LLM_PROVIDER` in `backend/.env`. The same config file controls the ingestion model, chat model, embedding model, and reranker.

**Supported providers:**

| Provider | `LLM_PROVIDER` value | Notes |
|---|---|---|
| Ollama | `ollama` | Default. Runs locally at `http://127.0.0.1:11434` |
| LM Studio | `lm_studio` | Local OpenAI-compatible server; exposes `reasoning_content` for thinking models |
| OpenAI | `openai` | Requires `OPENAI_API_KEY` |
| Google Gemini | `gemini` | Requires `GEMINI_API_KEY` |
| Anthropic | `anthropic` | Requires `ANTHROPIC_API_KEY` |
| HuggingFace | `huggingface` | Requires `HUGGINGFACE_API_KEY` |

A separate `INGESTION_LLM_MODEL` can be set to use a different (usually smaller) model for extraction vs. chat — for example, `gemma3:4b` for ingestion and `gemma4:latest` for chat.

An optional `LLM_FALLBACK_PROVIDER` kicks in if the primary provider fails.

---

## Runtime Model Switching

The provider, chat model, ingestion model, and server URL can be changed live from the `/settings` page — no server restart or `.env` edit required.

Changes are persisted to `data/runtime_config.json` and re-applied automatically on the next server start, so they survive restarts. API keys are never stored here — those remain in `backend/.env`.

| Field | What it controls |
|---|---|
| Provider | Active LLM backend (`ollama`, `lm_studio`, `gemini`, `openai`, `anthropic`, `huggingface`) |
| Chat model | Model used for all chat queries (`CHAT_MODEL` — highest-priority override) |
| Ingestion model | Model used during note ingestion — extraction, entity reasoning (`INGESTION_MODEL`) |
| Server URL | Base URL for local providers (LM Studio / Ollama) |

Model-only changes take effect on the next request with zero overhead. Provider or server URL changes trigger a full LLM client reinitialisation in-process.

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

### After Optimizations — Gemma4:e4b

Post-Final Implementation pipeline optimizations evaluated with Gemma4:e4b against the same HotPotQA benchmark. Improvements include refined answer synthesis, more targeted retrieval, reduced inter-query overhead, and an updated knowledge graph (fixing the Animorphs KB gap).

| Metric | Final Implementation | After Optimizations | Δ |
|---|---|---|---|
| **Exact Match (EM)** | 58.0% | **62.0%** | +4 pp |
| **Fuzzy Match** | 81.0% | **81.0%** | — |
| **Token F1** | 0.7366 | 0.7358 | −0.001 |
| **Contains expected** | 74.0% | 74.0% | — |
| **Hard failures** | 19 | 19 | — |
| **Fuzzy-only** | 23 | **19** | −4 |
| **Avg response time** | 212.10 s | 231.17 s | +19 s |
| **Retrieval Recall** | **0.715** | 0.610 | −0.105 |
| **Retrieval Precision** | 0.349 | **0.361** | +0.012 |
| **Retrieval F1** | **0.469** | 0.453 | −0.016 |
| **EM at full recall (Rc=1.0)** | 50% | **75%** | +25 pp |
| **EM at zero recall (Rc=0.0)** | 56% | **71%** | +15 pp |
| **Wall clock (100 Qs)** | ~8.75 h | **~6.5 h** | −2.25 h |

**Key takeaways:**

- **EM improves 4 pp (58% → 62%) with no change in fuzzy match** — gains are at the answer precision boundary, not in semantic correctness.
- **Answer synthesis at full recall dramatically improved.** EM at Rc=1.0 jumped 25 pp (50% → 75%), reversing the prior counter-intuitive result where excessive context hurt exact match.
- **Retrieval is more precise but less exhaustive.** Precision improved (+0.012) while recall dropped (−0.105) — the pipeline is more targeted, surfacing fewer gold documents overall but synthesising more accurately from the ones it finds.
- **Wall clock cut by 26%** — near-elimination of inter-query overhead reduced total wall clock from ~8.75 h to ~6.5 h.
- **Animorphs KB gap resolved** — the one question that failed in every prior run is now correctly answered (EM ✓, Rc=1.0, 146 s).

### Historical Architecture Progression

| Approach | Graph DB | Search | LLM | EM | Fuzzy | Avg response |
|---|---|---|---|---|---|---|
| Sub Questions (Feb 2026) | Neo4j | Elasticsearch | Gemini 3 Flash Preview | 62% | 75% | 50.5 s |
| Joint Approach (Mar 2026) | Neo4j | Elasticsearch | Gemini Flash Lite | 61% | — | ~43 s |
| Final Implementation (May 2026) | **Kuzu** | **Typesense** | Gemini Flash Lite | **59%** | 76% | **18.10 s** |
| Final Implementation (May 2026) | **Kuzu** | **Typesense** | Gemma4:e4b (local) | 58% | **81%** | 212.10 s |
| After Optimizations (May 2026) | **Kuzu** | **Typesense** | Gemma4:e4b (local) | **62%** | **81%** | 231.17 s |

The move from Neo4j + Elasticsearch to Kuzu + Typesense cut response time from ~43 s to 18.10 s (2.4×) while maintaining near-identical accuracy, and eliminated all external graph database and search service dependencies. Post-Final Implementation pipeline optimizations pushed Gemma4:e4b to **62% EM** — the highest exact match of any fully local configuration evaluated.

---

## Local Setup

### Prerequisites

- Docker Desktop (for Qdrant, Typesense, PostgreSQL, RustFS)
- Python 3.11+
- Node.js 20+
- ffmpeg (for server-side audio transcoding — `brew install ffmpeg` on macOS)
- Ollama (for local LLM/embedding inference)

### 1. Clone and install

```sh
git clone https://github.com/josetseph/LiveOS.git
cd LiveOS
```

### 2. Start infrastructure services

For local development (running the backend and frontend on your machine):

```sh
docker compose up -d postgres qdrant typesense rustfs
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

Run all first-time initialisation in one step (migrations, storage bucket, Qdrant collections, Typesense schema, Kuzu graph):

```sh
python scripts/init_local.py
```

Start the API server:

```sh
uvicorn app.main:app --reload --port 8700
```

### 4. Frontend

```sh
cd frontend
npm install
npm run dev
```

Open [http://localhost:3700](http://localhost:3700).

---

## Docker Deployment

To run the full stack in Docker (backend + frontend + all services):

```sh
cp backend/.env.example backend/.env
# edit backend/.env — set your LLM provider and API keys

docker compose up -d
```

The production compose file mounts `backend/.env` directly and **automatically overrides the service hostnames** — database, Qdrant, Typesense, and RustFS all resolve correctly inside Docker without touching your `.env`.

The only values you may need to update in `.env` before a Docker deployment are the LLM/embedding URLs, if you're pointing at a local model server. Inside a container, `127.0.0.1` refers to the container itself — use `host.docker.internal` to reach your machine:

| Variable | Dev `.env` value | Docker prod value |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:1234` | `http://host.docker.internal:1234` |
| `EMBEDDING_BASE_URL` | `http://127.0.0.1:11434` | `http://host.docker.internal:11434` |

If you use a cloud provider (Gemini, OpenAI, Anthropic) these don't apply — no `.env` changes are needed at all.

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

### LLM models

The LLM used for chat and ingestion is configured separately and served by one of the supported providers.

**Ollama (local)**

```sh
ollama pull gemma4:latest          # chat model
ollama pull gemma3:4b              # ingestion model (smaller, faster)
ollama pull qwen3-embedding:0.6b   # embedding model (required)
```

**LM Studio (local)**

1. Open LM Studio and go to the **Discover** tab
2. Search for a model by name (e.g. `google/gemma-3-4b-it`) and download it
3. Load the model and start the local server
4. Set `LLM_PROVIDER=lm_studio` in `backend/.env` — or switch provider live from `/settings`

Models can also be downloaded from [Hugging Face](https://huggingface.co/models) and loaded into LM Studio via **My Models → Load from disk**.

**Cloud providers**

Set the API key in `backend/.env` and configure `LLM_PROVIDER`:

```sh
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
LLM_MODEL=gemini-2.0-flash-lite
```

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

Individual reset scripts exist for each store: `reset_vectors.py`, `reset_index.py`, `reset_graph.py`, `reset_database.py`, `reset_storage.py`, `reset_ingestion.py`.

### Benchmark evaluation

Before running the benchmark, enable benchmark mode in `backend/.env`:

```sh
BENCHMARK_MODE=true
```

Full instructions — dataset ingestion, evaluation flags, and LLM model setup — are in [`backend/tests/benchmark/README.md`](backend/tests/benchmark/README.md).

```sh
cd backend
source venv/bin/activate

# Ingest the benchmark notes
python tests/benchmark/prepare_dataset.py --dataset hotpotqa

# Run evaluation
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose
```

Results are written to `backend/tests/benchmark/results/` as timestamped JSON files, and to `Results/` as Markdown reports.

---

## Knowledge Bases

LiveOS supports multiple isolated knowledge bases. Each KB maintains its own:

- **Kuzu graph** — separate database directory under `data/kuzu/<slug>/`
- **Qdrant collections** — `<slug>_node_cores`, `<slug>_node_relationships`, `<slug>_node_isolated_contexts`
- **Typesense collection** — `<slug>_nodes`
- **Notes** — filtered by `kb_id` in PostgreSQL

KBs are managed by `KBRegistry` (`backend/app/services/kb_registry.py`), a JSON-persisted singleton at `data/kb_registry.json`. The `default` KB always exists and cannot be deleted or renamed — it maps to the original single-KB configuration.

The active KB is selected via a `?kb=<slug>` query parameter on all API endpoints. The frontend stores the active KB in `localStorage` and displays its name in the sidebar. All routes — notes, chat, graph — are automatically scoped to the active KB.

To manage knowledge bases, open `/kb` in the frontend or use the API:

```sh
# List all KBs
GET /api/v1/kb

# Create a KB
POST /api/v1/kb          { "name": "Work" }

# Rename a KB
PATCH /api/v1/kb/{id}    { "name": "New Name" }

# Delete a KB (drops all data)
DELETE /api/v1/kb/{id}
```
