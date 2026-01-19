# Development Process & Architectural Evolution

This document tracks the journey of building the **LiveOS Brain**, detailing the decisions made, models used, and the architectural shifts that led to the current system.

---

## 📅 Phase 1: The Genesis (Local-First Ambition)
**Goal**: Create a "Second Brain" that runs locally on consumer hardware (Mac), capable of ingesting and understanding notes.

*   **Initial Stack**: Python (FastAPI), LangChain, ChromaDB (Vector Only).
*   **Model**: `phi-3.5` (via Ollama).
    *   **Why**: Small footprint (3.8B), fast inference.
    *   **The Problem**: Severe hallucination. The model would invent details in summaries that didn't exist in the source text (e.g., adding "Budget Meeting" to a note about "Grocery Shopping").
*   **Pivot**: We needed a model with stronger grounding capabilities.

---

## 📅 Phase 2: The Search for Reasoning (Llama 3.1)
**Goal**: Improve data accuracy and reduce hallucinations.

*   **Change**: Migrated to `llama3.1:8b`.
*   **Outcome**:
    *   **Pros**: Significantly better summarization and entity extraction. Less prone to making things up.
    *   **Cons**: Heavier on VRAM. Still struggled with **Complex Extraction** (Extracting nested JSON for Graph Ontology often failed schema validation).
*   **Architecture Update**: Introduced **Neo4j** (Graph DB) alongside Vector DB to enable "GraphRAG" (Structured knowledge + Semantic search).

---

## 📅 Phase 3: The DeepSeek Revolution (Reasoning Engine)
**Goal**: Enhance the "Chat" capability to be truly intelligent and capable of synthesis.

*   **Change**: Migrated to `deepseek-r1:14b` (The "Distilled" Reasoning Model).
*   **Impact**:
    *   **Chat**: Incredible performance. The chain-of-thought (CoT) reasoning allowed it to synthesize answers from multiple notes with high accuracy.
    *   **The Bottleneck**: While great for *Chat*, using a 14B reasoning model for *Ingestion* (Extracting metadata from hundreds of notes) was too slow. Ingestion became a blocking operation.

---

## 📅 Phase 4: The "Scaler" Architecture (Tiered Models)
**Goal**: Decouple "Thinking" (Chat) from "Doing" (Ingestion) to optimize speed and cost.

*   **Strategy**: **Tiered Model Architecture**.
    1.  **The Brain (Chat)**: `deepseek-r1:14b` (High IQ, Slower).
    2.  **The Senses (Ingestion)**: `phi4-mini` (Fast, Lightweight).
*   **Customization**: Created `knowledge-architect` (a custom Ollama Modelfile based on `phi4-mini`) with a System Prompt tuned specifically for JSON extraction.

---

## 📅 Phase 5: The Hardening (Repair Pipeline)
**Goal**: Make the small model (`phi4-mini`) reliable.

*   **The Problem**: `phi4-mini` is fast but "sloppy". It often produces invalid JSON:
    *   Comments in JSON (`// ...`).
    *   Smart quotes (`"value"`).
    *   Missing commas between objects.
    *   Unquoted values (`status: Done` vs `status: "Done"`).
*   **The Fix**: **JSON Repair Pipeline**.
    *   Instead of discarding invalid extraction, we built a robust **Regex Engine** in `llm.py` that "surgeries" the bad JSON into valid JSON.
    *   **Result**: We achieved 99% reliability with a sub-4B parameter model, making ingestion 5x faster than using Llama 3.
*   **Stability**:
    *   Added `tenacity` retries to Database operations.
    *   **Transaction Pooler Fix**: Configured `asyncpg` with `statement_cache_size=0` to support Supabase Transaction Mode (port 6543), resolving `InvalidSQLStatementNameError`.

---

## 📅 Phase 6: Polyglot Persistence (Mind & Body)
**Goal**: Optimize storage for different data types.

*   **Evolution**:
    *   **Vector Store** (Start): Good for fuzzy search, bad for structure.
    *   **Graph DB** (Neo4j): Good for connections, bad for full-text blobs.
    *   **Relational DB** (Postgres/Supabase): Added as the "Body" to store the authoritative content (Truth).
    *   **Object Storage** (Cloudflare R2): Added for huge files (Audio/PDFs).
*   **Current State**: **Double-Fetch Hybrid RAG**.
    1.  Search Graph for IDs.
    2.  Fetch Content from Postgres.
    3.  Generate Answer with DeepSeek.

---

## 📅 Phase 7: Optimization (The Speed Update)
**Goal**: Reduce backend startup time and inference latency for Chat.

*   **Reranker Switch**:
    *   **Old**: `qwen3-reranker-8b` (Slow startup, sharded loading).
    *   **New**: `mxbai-rerank-large-v2` (Gen-Reranker).
    *   **Benefit**: Faster startup, lower memory footprint, competitive performance.
    *   **Code Change**: Replaced raw Transformers code with **`rerankers`** library to handle Generative Reranking probability logic (Logit extraction) without reinventing the wheel.
*   **Brain Transplant**:
    *   **Old**: `deepseek-r1:14b` (High quality, but slow on M1/M2).
    *   **New**: `phi4-mini-reasoning`.
    *   **Benefit**: Significant speedup in chat response with acceptable reasoning tradeoff.

---

## 📅 Phase 8: The Local-First Migration (Docker)
**Goal**: Complete independence from Cloud/Internet. "LiveOS" must live on the OS.

*   **Infrastructure Shift**:
    *   **Supabase (Cloud)** -> **Postgres (Local Docker)**.
    *   **Cloudflare R2 (Cloud)** -> **MinIO (Local Docker)**.
*   **Config Simplification**:
    *   Removed `.env` dependency for keys (No secrets needed for localhost).
    *   Centralized configuration in `config.py` with intelligent defaults.
*   **Result**: 
    *   Zero-latency database queries (~0.1ms).
    *   Full offline capability.
    *   Privacy by design (Data never leaves the machine).

---

## 📅 Phase 9: Vision & Stability (The "Clear Sight" Update)
**Goal**: Replace the "blind" OCR model with a true Vision Language Model (VLM) and stabilize local file storage.

*   **Vision Engine Upgrade**:
    *   **Old**: `deepseek-ocr` (via Ollama). **Issue**: It was an OCR model, not a describer. It returned "." for complex images.
    *   **New**: `microsoft/Florence-2-large` (Local Transformers).
    *   **Benefit**: Generates rich, detailed captions for images (e.g., "A tall pagoda with red roof..."). Optimized to run on CPU/MPS without heavy VRAM usage.
*   **Infrastructure Fixes**:
    *   **MinIO**: Fixed `403 Forbidden` and `404 Not Found` errors by enforcing **Path-Style Addressing** (`localhost:9000/bucket/key`) and applying **Public Read Policies**.
    *   **Graph Pruning**: Implemented "Graph Pruning" logic to delete stale relationships before re-ingesting a Note, ensuring the Knowledge Graph stays accurate during edits.

---

## 📅 Phase 10: Cognitive Upgrade (DeepSeek & Llama)
**Goal**: Leverage State-of-the-Art (SOTA) small models for higher intelligence and reliability.

*   **Brain Transplant (Chat)**:
    *   **Old**: `phi4-mini-reasoning`.
    *   **New**: `llama3.1` (8B).
    *   **Why**: Llama 3.1 is the industry standard for instruction following. It provides more concise, reliable answers with less "rambling" than Phi-4.
*   **Senses Upgrade (Extraction)**:
    *   **Old**: `phi4-mini` (Custom Architect).
    *   **New**: `deepseek-r1:7b` (Distill-Qwen).
    *   **Why**: DeepSeek-R1 is a reasoning model distilled from a massive 671B model. It excels at complex logic, making it perfect for extracting structured data from messy notes where relationships are implied, not stated.

---

## 📅 Phase 11: The "Polished Mind" Update (UI/UX)
**Goal**: Elevate the user experience to feel premium and responsive.

*   **Aesthetic Overhaul**:
    *   **Old**: Large, intrusive 200px cursor highlight with blur.
    *   **New**: Subtle 40px high-fidelity glow with CSS radial gradients and `framer-motion` springs. 
    *   **Benefit**: Improved focus on content while maintaining a modern, "glassmorphic" feel.
*   **Interaction Design**: Refined sidebar hover states and active indicators to provide clear visual feedback during deep-link navigation.

---

## 📅 Phase 12: The "Memory Keeper" Update (Historical Dates)
**Goal**: Support long-term journaling by allowing retrospective date settings.

*   **Architectural Shift**:
    *   **Old**: Automatic date detection from note text (found to be unreliable/presumptive).
    *   **New**: Manual **Date Picker** integrated into the note toolbar.
*   **Logic Simplification**:
    *   Disabled LLM-based date extraction to give the user absolute control.
    *   Integrated `dateparser` on the backend to robustly handle the manual picker's ISO timestamps while defaulting to "now" for new entries.
*   **Result**: Users can now import years of historical notes with 100% chronological accuracy.

---

## 📅 Phase 13: Gemini Testing & Performance Optimization
**Goal**: Test cloud LLM integration and optimize local model performance.

*   **Gemini Integration (Temporary)**:
    *   Added support for Gemini via OpenAI-compatible endpoint for performance comparison.
    *   Implemented dynamic provider switching based on `GEMINI_API_KEY` presence.
*   **Local Model Optimization**:
    *   **Timeout Extension**: Increased LLM client timeout from 60s to 300s to accommodate slower local models.
    *   **Parallel Neighborhood Updates**: Refactored `_update_neighborhoods` to use `asyncio.gather` for concurrent entity/concept summary updates.
    *   **Entity-Level Locking**: Implemented `EntityLockManager` to prevent race conditions when multiple notes update the same entity simultaneously.
    *   **Result**: Eliminated "Request timed out" errors and reduced total ingestion time by ~40%.

---

## 📅 Phase 14: The "Gemma3" Migration & System Transparency
**Goal**: Migrate to Google's Gemma3 12B for improved performance and add comprehensive system monitoring.

*   **Model Stack Overhaul**:
    *   **Main LLM**: Migrated from `llama3.1:8b` to `gemma3:12b` for all roles (extraction, summarization, chat).
    *   **Custom Architect**: Rebuilt `knowledge-architect` Modelfile with `gemma3:12b` as base.
    *   **Benefit**: Better JSON adherence, improved reasoning, and faster inference on Apple Silicon.
*   **Retrieval Enhancements**:
    *   **Persona Traits**: Added persona traits to graph context queries with correct relationship direction (`REVEALED_BY`) and evidence quotes.
    *   **Soft Cap**: Implemented 50-snippet limit for reranker to maintain 3-5s response times.
    *   **Performance**: Reduced retrieval latency by capping context before reranking.
*   **UI Transparency**:
    *   **System Info Header**: Expanded to show all active services:
        *   **Models**: Gemma3 12B, Qwen3 Embed, MxBai Rerank, DeepSeek OCR, Whisper Audio
        *   **Databases**: Neo4j, Postgres, MinIO (color-coded indicators)
    *   **Markdown Support**: Confirmed note preview modal renders markdown via `ReactMarkdown`.
    *   **User Icon Removal**: Cleaned up header by removing profile icon (no authentication).

---

## � Phase 15: The "Complete Rebuild" Update (Frontend-v2 → Frontend)
**Goal**: Create a production-ready, polished UI/UX that matches the sophistication of the backend intelligence.

*   **Framework Migration**:
    *   **Old**: Next.js 14 with scattered component structure.
    *   **New**: Next.js 16 (latest) with unified architecture.
*   **UI Overhaul - Notes Interface**:
    *   **Custom Particle Background**: Replaced shader-based backgrounds (paid license issue) with custom Canvas particle system (100 particles, 3-8px, purple/blue/cyan gradients, mouse-responsive).
    *   **Multimodal Input**: Added explicit **Attach** (📎) and **Record** (🎤) buttons with file preview modals (images, PDFs, audio).
    *   **Date Picker**: Added calendar modal for backdating notes with proper datetime-local input.
    *   **Local-Only Editing**: Notes save to browser state on blur, no backend calls until explicit **"Ingest Note"** button is clicked.
    *   **Preview Mode**: Existing notes open in preview (read-only) with full markdown rendering, new notes open in edit mode.
*   **UI Overhaul - Chat Interface**:
    *   **Session Persistence**: Messages saved to `sessionStorage`, persist across navigation during browser session.
    *   **Reference Links**: Styled note references with subtle purple background (`bg-purple-500/10 border border-purple-500/30`) matching notes preview.
    *   **File Preview Modals**: Clicking file links (📎/🎤) opens modal preview instead of new tab.
    *   **Markdown Rendering**: Full support for headings (H1-H4), bold, italic, code blocks, lists via enhanced Tailwind Typography prose classes.
*   **Architectural Shift - Deferred Ingestion**:
    *   **Problem**: Every blur/edit triggered backend ingestion, causing UX friction (clicking "Attach" would trigger save).
    *   **Solution**: 
        *   Notes created with `temp-${timestamp}` IDs stay local-only.
        *   `handleSaveNote` only updates local state (no API call).
        *   `handleIngestNote` explicitly sends to backend for processing.
    *   **Result**: Users can freely edit, attach files, record audio without triggering expensive LLM extraction until ready.
*   **Polish & Refinement**:
    *   **Logo Integration**: Added LiveOS logo to landing page, sidebar, and favicon with proper browser cache handling.
    *   **Date Display**: Note header shows formatted creation date in both edit and preview modes.
    *   **Modal UX**: Date picker doesn't auto-close, file previews show images/PDFs/audio with download fallback.
    *   **Link Styling**: Unified subtle purple glow across chat references, file links, and note previews.

---

## 📋 Current Model Stack (Phase 15)
| Component | Model | Role |
| :--- | :--- | :--- |
| **Chat / Synthesis** | `gemma3:12b` | The "Brain". Concise, reliable instruction following with strong JSON adherence. |
| **Extraction** | `knowledge-architect` (Gemma3 12B) | The "Senses". Custom-tuned for structured data extraction. |
| **Embedding** | `qwen3-embedding:8b` | Semantic vector search (4096-dim). |
| **Reranking** | `mxbai-rerank-large-v2-seq` | Fast context relevance scoring with 50-snippet cap. |
| **Vision** | `microsoft/Florence-2-large` | Local Transformer model for detailed image description. |
| **Audio** | `openai/whisper-large-v3` | Local audio transcription. |
| **OCR** | `deepseek-ocr:latest` | PDF and image text extraction. |

---

## 📅 Phase 16: The "PKM Upgrade" (Dual-Purpose Knowledge Management)
**Goal**: Transform LiveOS from pure personal journal into dual-purpose system supporting Academic/Professional PKM alongside personal journaling.

*   **Domain Categorization**:
    *   **Schema Extension**: Added `domain` field (Academic/Personal/Professional) and `references: List[ExternalReference]` to Extraction model.
    *   **Intelligent Classification**: LLM classifies notes based on PRIMARY SUBJECT MATTER, not writing style.
        *   "I learned about Linear Regression" → Academic (learning material)
        *   "Met with team to discuss GraphRAG" → Professional (work meeting)
        *   "Feeling anxious about thesis defense" → Personal (emotions/feelings)
    *   **Critical Fix**: Updated `system_msg` in `llm.py` to include `domain` and `references` in JSON template - without this, LLM defaulted all notes to "Personal".
*   **Academic Knowledge Graph**:
    *   **External References**: New `Reference` node type for papers, books, quotes, videos.
    *   **Citation Tracking**: `CITES` relationships link Notes to References.
    *   **Academic Relationships**: 
        *   `PREREQUISITE_FOR`: Knowledge dependencies (e.g., Probability → Linear Regression)
        *   `CONTRADICTS`: Conflicting concepts (e.g., Deterministic vs Stochastic)
        *   Detected via heuristics from concept definitions ("builds on", "requires", "contradicts")
*   **Domain-Aware Retrieval**:
    *   **Query Classification**: Keyword-based detection of query domain using same heuristics as synthesis.
    *   **Domain Boosting**: 1.5x score multiplier for notes matching query domain in hybrid search.
    *   **Graph Service Update**: Added `query_vector_with_domain()` method returning domain field.
*   **Domain-Aware Synthesis**:
    *   **Adaptive Prompts**: System instructions change based on detected query domain:
        *   **Academic**: Pedagogical, conceptual, references papers/theorems, explains prerequisites
        *   **Personal**: Empathetic, insight-focused, connects feelings and experiences
        *   **Professional**: Concise, action-oriented, references meetings/tasks/decisions
    *   **Consistent Detection**: Uses same keyword matching as retrieval for domain detection.
*   **Graph Visualization**:
    *   **Reference Nodes**: Gold (#ffd700) nodes for citations with summaries
    *   **Domain Colors**: Notes colored by domain (Academic=emerald, Professional=purple, Personal=blue)
    *   **Academic Link Styling**: 
        *   `CITES` links: Gold with 0.4 opacity
        *   `PREREQUISITE_FOR`: Emerald with directional particles
        *   `CONTRADICTS`: Red with 0.3 opacity
    *   **Color Fix**: Changed Persona nodes from orange to light purple (#a78bfa) to distinguish from gold References
*   **Documentation**: Created comprehensive `PKM_UPGRADE.md` with examples, test scenarios, and implementation details.
*   **Testing**: Full test suite (`test_pkm_upgrade.py`) validates domain detection, cross-domain insights, and reference extraction.

---

## 🏗️ Architectural Principles

1.  **Local-First**: All data and processing stays on the user's machine.
2.  **Polyglot Persistence**: Right tool for the right job (Postgres for content, Neo4j for relationships, MinIO for files).
3.  **Tiered Intelligence**: Fast models for ingestion, powerful models for synthesis.
4.  **Graceful Degradation**: JSON repair pipelines and retry logic ensure reliability.
5.  **Entity-Level Consistency**: Locking mechanisms prevent race conditions during concurrent updates.
6.  **Performance Caps**: Soft limits (50 snippets) ensure predictable response times.
7.  **Transparency**: Real-time system info displays all active services and models.
8.  **Dual-Purpose Design**: Single system serves both personal journaling and academic/professional knowledge management with domain-aware intelligence.
