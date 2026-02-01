# LiveOS Brain (Core System)

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

LiveOS Brain is a multimodal, graph-based personal memory system. It ingests notes, audio, images, and PDFs, understands their semantic meaning, and creates a living ontology (knowledge graph) of your life.

> **Project History**: For a detailed log of the architectural evolution and model choices, see [Development Process](./development_process.md).

## System Architecture

The system operates on a **Polyglot Persistence** model ("Mind & Body") with **adaptive knowledge management** across multiple domains: Personal Journal, Academic/Professional PKM, and Creative Writing.

**Why Multi-Purpose?** A single system that handles personal reflections ("I'm anxious about my thesis"), academic learning ("Markov Chains have the memoryless property"), and creative expression ("The moon is a ghost") with domain-aware intelligence. The system automatically detects the note's purpose and adapts retrieval and synthesis accordingly.

### Multi-Mode Operation

**Personal Journal Mode:**
- Daily activities, feelings, goals, relationships
- Tasks and persona trait tracking
- Emotional pattern analysis

**Academic/Professional PKM:**
- Learning notes, papers, concepts, theorems
- Citation tracking and reference management
- Knowledge graph with prerequisites and contradictions
- Domain-aware retrieval and synthesis

**Creative Mode:**
- Poems, stories, lyrics, and metaphors
- Focus on themes, imagery, and emotional resonance
- Non-judgmental, advice-free synthesis that respects artistic voice

```mermaid
graph TD
    User[User / Frontend]
    User -->|Notes, Files, Audio| API[FastAPI Backend]
    
    subgraph Storage [Polyglot Persistence]
        API -->|CRUD Content| Postgres[(Local Postgres)]
        API -->|Graph/Vector| Neo4j[(Local Neo4j)]
        API -->|Files| MinIO[(Local MinIO)]
    end

    subgraph Ingestion Pipeline [Agentic Ingestion]
        API --> Workflow[Ingestion Agent - LangGraph]
        Workflow --> Multimedia[Multimedia Node]
        Multimedia -->|Whisper Audio| Transcribe[Audio Transcription]
        Multimedia -->|Paddle OCR| OCR[PDF]
        Multimedia -->|Florence 2| OCR[Image Processing]
        Multimedia -.->|Sync Content| Postgres
        
        Transcribe --> Extractor[Knowledge Architect - Gemma3 4B]
        OCR --> Extractor
        Extractor -->|Domain Detection| DomainClassifier{Personal/Academic/Professional}
        DomainClassifier -->|JSON Repair| Cleaner[JSON Repair Pipeline]
        Cleaner -->|Entities & Concepts| Embedder[Qwen3 Embedding 0.6B]
        Embedder -->|Vectors + Metadata| Neo4j
        Embedder -->|Academic Relationships| AcademicGraph[PREREQUISITE_FOR, CONTRADICTS, CITES]
        Embedder -->|Summaries| Summarizer[Neighborhood Updates]
        Summarizer -->|Entity-Level Locking| Neo4j
    end
    
    subgraph Retrieval Pipeline [GraphRAG]
        User -->|Query| QueryClassifier{Detect Domain}
        QueryClassifier -->|Academic/Personal/Pro| Search[Hybrid Search + Domain Boost]
        Search -->|1. Vector Scan| Neo4j
        Search -.->|2. Fetch Content| Postgres
        Search -->|3. Graph Expansion| Neo4j
        Search -->|4. Symbolic Ranking| Ranker[Priority Scoring - Primary 100, Secondary 50]
        Ranker -->|Top Context| Synthesis[Domain-Aware Synthesis]
        Synthesis --> User
    end
```

---

---

## 🚀 Getting Started

### Option 1: Local Development (Recommended for Development)

The system runs locally using Docker for services and Ollama for models.

#### Prerequisites
*   **Docker Desktop** (or Engine)
*   **Ollama**: Installed and running (`ollama serve`).
*   **Python 3.11+**
*   **Node.js 20+**

#### Steps
1.  **Start Services**:
    ```bash
    docker compose up -d
    ```

2.  **Backend Setup**:
    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # Create Database Tables & Storage Bucket
    python scripts/init_local.py

    # Start API Server
    uvicorn app.main:app --reload
    ```

3.  **Frontend Setup**:
    ```bash
    cd frontend
    npm install
    npm run dev
    ```

4.  **Access**:
    *   Frontend: `http://localhost:3000`
    *   Backend API: `http://localhost:8000/docs`
    *   Neo4j Browser: `http://localhost:7474`
    *   MinIO Console: `http://localhost:9001`

---

### Option 2: Production Deployment (All-in-One Docker)

Deploy the entire stack with a single command (requires Ollama running on host).

#### Prerequisites
*   **Docker** & **Docker Compose**
*   **Ollama** installed on host machine with models pulled

#### Steps
1.  **Pull Ollama Models** (on host):
    ```bash
    ollama pull gemma3:4b
    ollama pull qwen3-embedding:0.6b
    ollama pull MedAIBase/PaddleOCR-VL:0.9b
    ```

2.  **Download Hugging Face Models** (pre-bundled in repo):
    *   **Florence-2-Large** (Vision): [`microsoft/Florence-2-large`](https://huggingface.co/microsoft/Florence-2-large)
    *   **Whisper V3 Turbo** (Audio Transcription): [`openai/whisper-large-v3-turbo`](https://huggingface.co/openai/whisper-large-v3-turbo)
    
    These models will need to be downloaded into the `backend/models/` folder and will be copied into the Docker image during build.

3.  **Deploy Full Stack**:
    ```bash
    docker compose -f docker-compose.prod.yml up -d
    ```

4.  **Access**:
    *   Frontend: `http://localhost:3000`
    *   Backend API: `http://localhost:8000`

5.  **Monitor Logs**:
    ```bash
    docker compose -f docker-compose.prod.yml logs -f backend
    ```

**Note**: The init container automatically creates database tables and MinIO buckets on first run.

---

## ️ Maintenance & Reset

### How to Completely Reset the System
If you want to wipe all data (Notes, Graph, Vectors, Files) and start fresh:

1.  **Stop everything**: `Ctrl+C` in your terminals.
2.  **Run the Reset Script**:
    ```bash
    cd backend
    python scripts/reset_db_and_verify.py
    ```
    *This script will wipe the Neo4j Graph, Postgres Tables, and MinIO Bucket.*

### How to Manage Models
The system uses Ollama models for LLM inference. To update models:
```bash
# Pull latest versions
ollama pull gemma3:4b
ollama pull qwen3-embedding:0.6b
ollama pull MedAIBase/PaddleOCR-VL:0.9b
```

---

## 1. The Ingestion Pipeline ("The Senses")

When you create a note or upload a file, it enters the **Ingestion Agent** (`app/workflows/agents/ingestion_agent.py`), a LangGraph-based workflow with entity-level locking for data consistency.

1.  **Multimedia Processing**:
    *   **Unified Pipeline**: Detects file links `[📎 Filename](URL)` and processes them.
    *   **Audio**: `.webm`/`.mp3`/`.m4a` are transcribed via **Whisper Large V3 Turbo** (local). Transcripts sync to Postgres.
    *   **Images**: Described via **Florence-2-Large** (Local Transformer).
    *   **PDFs**: OCR'd via **Paddle OCR** (Ollama).
    *   **Historical Dates**: Backdate notes using the **Date Picker** in the toolbar. The system uses `dateparser` for robust parsing of user-selected dates.

2.  **Cognition (Extraction)**:
    *   **Model**: `gemma3:4b` - Lightweight model optimized for structured JSON extraction.
    *   **Schema**: Strict JSON extraction for `Entities`, `Concepts`, `Tasks`, `Persona`, `Domain`, `References`.
    *   **Domain Classification**: Automatically categorizes notes as Academic/Personal/Professional/Creative/Dreams based on primary subject matter.
    *   **Reference Extraction**: Captures citations (papers, books, quotes) with full attribution for academic notes.
    *   **Isolated Context Detection**: Identifies facts that are only true within the note's context (e.g., "today" references).
    *   **Schema Normalization**: Handles LLM inconsistencies (capitalized keys, string importance values, status variations) via Pydantic validators.
    *   **Entity Deduplication**: Normalizes names (strips `#` prefix, applies `.title()` case) to prevent duplicate nodes.
    *   **JSON Repair Pipeline**: A robust regex layer fixes common LLM syntax errors (comments, smart quotes, control characters, markdown fences).
    *   **Entity-Level Locking**: Prevents race conditions when multiple notes update the same entity concurrently.

3.  **Embedding & Graph Storage**:
    *   **Embedding**: `qwen3-embedding:0.6b` generates 1024-dim vectors - optimized for speed on consumer hardware.
    *   **Graph**: Neo4j stores the ontology with relationships (`MENTIONS`, `CONTRIBUTES_TO`, `PRODUCES_TASK`, `REVEALED_BY`).
    *   **Bi-Temporal Relationships**: Each relationship tracks `valid_from` (event time), `ingested_at` (system time), `valid_to`, and `is_active`.
    *   **Community Assignment**: Nodes are automatically assigned to domain-based Community clusters (Professional, Academic, Personal, Creative, Dreams).
    *   **Soft Invalidation**: Contradicted relationships are marked `is_active=false` with `valid_to` timestamp instead of deletion.
    *   **Neighborhood Summaries**: Parallel updates with async locking ensure data integrity.

---

## 2. The Retrieval System ("The Voice")

1.  **Semantic Snippet Retrieval Pipeline**:
    *   **Step 1: LLM Query Analysis**: Uses structured outputs to extract intent, entities, concepts, and temporal signals from the query
    *   **Step 2: Graph Nodes** (Long-Term Wisdom): Search unified knowledge graph index (20 distilled Concepts, Entities, Tasks, Personas, References)
    *   **Step 3: Recent Notes** (Short-Term Memory): Fetch 20 most recent notes for current context
    *   **Step 4: Linked Evidence**: Trace back from graph nodes to source notes that formed them
    *   **Step 5: Chunking**: Split all note content into overlapping snippets (400 chars, 100 overlap)
    *   **Step 6: Relationship Expansion**: Expand graph nodes with related nodes before ranking
    *   **Step 7: Symbolic Ranking**: Score all candidates using pure priority-based scoring (no neural reranker)

2.  **Pure Symbolic Ranking**:
    *   **Philosophy**: Trust the graph. If the user asks about "svtlottery", nodes named "svtlottery" are definitionally relevant.
    *   **Primary Nodes** (name matches query entities): `base_score = 100.0`, marked `symbolic_immune = True`
    *   **Secondary Nodes** (related via graph): `base_score = 50.0`
    *   **Final Score**: `base_score × entity_boost × keyword_boost`
    *   **Performance**: Instant ranking (~0.0001s vs ~2.0s with neural reranker)

3.  **Smart Query Analysis**:
    *   **LLM-Powered**: Uses Gemma3 structured outputs to extract intent, entities, and concepts
    *   **Heuristic Fallback**: Detects capitalized words, quoted terms, words after "at/with/about/for/working"
    *   **Entity Detection**: Extracts mentioned entity/concept names for priority scoring
    *   **Example Behavior**: "job at livecops" → "livecops" detected as entity, nodes named "livecops" get primary priority

4.  **Fact Pool Context Format**:
    *   **Unified Format**: Single pool of evidence with semantic labels instead of rigid sections
    *   **`[CORE CONSENSUS]`**: Graph consensus summaries (highest trust)
    *   **`[RELATED CONTEXT]`**: Related node summaries
    *   **`[DOMAIN OVERVIEW]`**: Community-level summaries
    *   **`[CONNECTION PATH]`**: Multi-hop relationship chains
    *   **Design**: LLM synthesizes across all facts naturally rather than treating sections separately

5.  **Conversational "Thoughtful Peer" Synthesis**: **Gemma3 4B** with persona-based prompting:
    *   **Style**: "Write like a thoughtful peer reflecting back"
    *   **No Rigid Headers**: Avoids formulaic "DIRECT ANSWER:" or "KEY INSIGHTS:" patterns
    *   **Natural Voice**: "You mentioned..." rather than "The notes reveal..."
    *   **Strict Grounding**: Every claim must trace to context, no invented information
    *   **Domain-Aware**: Adapts tone for Academic/Personal/Professional/Creative content

---

## 3. Technology Stack

*   **Backend**: Python 3.11 (FastAPI, LangGraph, AsyncPG, Instructor, Tenacity)
*   **Frontend**: Next.js 16 (React 19, Tailwind v4, Framer Motion, React Force Graph)
*   **Aesthetics**: High-fidelity cursor effects with subtle glows, glassmorphism, and micro-animations.
*   **Infrastructure** (Docker):
    *   **Postgres**: Authoritative content (Port 5433)
    *   **Neo4j**: Knowledge Graph & Vectors (Port 7474)
    *   **MinIO**: Local S3-compatible storage (Port 9000/9001)
*   **LLM Stack** (Ollama):
    *   **Main LLM**: Gemma3 4B (Extraction, Summarization, Chat)
    *   **Embedding**: Qwen3 Embedding 0.6B (1024-dim)
    *   **Ranking**: Pure Symbolic (no neural reranker)
    *   **Vision**: Florence-2-Large (Transformers)
    *   **Audio**: Whisper Large V3 Turbo (Transformers)
    *   **OCR**: PaddleOCR-VL 0.9B (Ollama) - Optimized for resource efficiency

### Audio Model Selection

**Whisper-Large-V3-Turbo vs Whisper-Large-V3 Testing:**

| Metric | Whisper V3 Turbo | Whisper V3 |
|--------|-------------------|------------|
| **Duration (1 min audio)** | **12.17s** | 34.96s |
| **Speed** | **325 words/min** | 100 words/min |
| **Accuracy** | High (66 words) | High (58 words) |

**Decision:** Switched to **Whisper Large V3 Turbo** for production.
- **3× Faster transcription speed** (12s vs 35s)
- **Higher word recovery** (detected 14% more words in test samples)
- **Reduced latency** for real-time voice interaction

### OCR Model Selection

**PaddleOCR-VL vs DeepSeek-OCR Testing:**

| Metric | PaddleOCR-VL 0.9B | DeepSeek-OCR Latest |
|--------|-------------------|---------------------|
| **Model Size** | 935 MB | 6.7 GB |
| **Speed (CV)** | 0.48s | 0.01s |
| **Speed (Book - 300 pages)** | 2.17s | 1.98s |
| **Quality** | ✅ Identical | ✅ Identical |
| **Resource Usage** | 🟢 Low VRAM | 🟡 High VRAM |

**Decision:** Using **PaddleOCR-VL** for production due to:
- **7× smaller model size** (935 MB vs 6.7 GB)
- **Identical OCR quality** (tested on CV and technical books)
- **Comparable speed** on multi-page documents (2.17s vs 1.98s)
- **Resource efficiency** - Critical for local deployment on consumer hardware
- **Multi-language support** - Better internationalization than DeepSeek-OCR

While DeepSeek-OCR is faster on single pages (0.01s vs 0.48s), the difference becomes negligible on real-world documents with multiple pages. The 7× reduction in model size makes PaddleOCR-VL the optimal choice for LiveOS's local-first architecture.

---

## 4. Key Features

*   **Multi-Domain PKM**: Unified system for personal journaling, academic learning, professional work, and creative expression
*   **Domain-Aware Intelligence**: Automatic categorization with adaptive retrieval and synthesis
*   **Academic Knowledge Graph**: Citation tracking, prerequisite chains, contradiction detection
*   **Multimodal Ingestion**: Text, Audio, Images, PDFs
*   **GraphRAG**: Semantic search + Knowledge graph traversal with domain boosting
*   **Community Summaries**: Microsoft GraphRAG-style domain clusters for broad/exploratory queries
*   **Bi-Temporal Tracking**: Separates event time (when fact became true) from system time (when recorded)
*   **Historical Journaling**: Manual date picker for backdating notes with proper temporal accuracy
*   **Soft Invalidation**: Contradicted relationships marked inactive instead of deleted, preserving history
*   **Entity-Level Locking**: Prevents data corruption during concurrent updates
*   **Parallel Neighborhood Updates**: Faster ingestion with `asyncio.gather`
*   **Symbolic Ranking**: Pure priority-based scoring (primary=100, secondary=50) for instant, grounded retrieval
*   **Extraction Robustness**: Schema normalization, type coercion, and JSON repair handle LLM inconsistencies
*   **Entity Deduplication**: Automatic name normalization prevents duplicate nodes (`#project` = `project`)
*   **Unified Isolated Context**: All extracted types (Entity, Concept, Task, Persona, Reference) use consistent `isolated_context` field
*   **Markdown Support**: Note previews render markdown in chat
*   **Real-time System Info**: Header displays all active services and databases
*   **Dual Graph Visualization**: 2D Force Graph and 3D WebGL graph with Community clusters

---

## 5. Batch Processing & Testing

### Batch Note Processing (`batch-note-processing/`)

For bulk ingestion of notes from text files, use the batch processing scripts:

**Scripts:**
- `send_note.py` - Send individual notes to the ingestion endpoint
- `batch_ingest.py` - Batch process all `.txt` and `.md` files from `notes/` directory

**Usage:**
```bash
cd batch-note-processing

# Single note
python send_note.py "Your note content"
python send_note.py --file my-note.txt
python send_note.py "Historical note" --date "2024-01-15"

# Batch processing
python batch_ingest.py
python batch_ingest.py --dry-run              # Preview without sending
python batch_ingest.py --delay 1              # Add 1s delay between notes
python batch_ingest.py --auto-date            # Extract dates from filenames
```

**Auto-date filename patterns:**
- `2024-01-15-my-note.txt` → Uses 2024-01-15
- `note-2024-01-15.md` → Uses 2024-01-15
- `20240115_meeting.txt` → Uses 2024-01-15

**Features:**
- 📂 Automatically processes all `.txt` and `.md` files
- 📅 Extracts dates from filenames (optional)
- ⏳ Configurable delay to avoid overwhelming the system
- 🔍 Dry-run mode for previewing
- 📊 Summary report with success/failure counts

---

## 📚 PKM (Personal Knowledge Management) Capabilities

LiveOS now supports **multi-domain knowledge management** for personal journaling, academic/professional learning, and creative work. For full details, see [PKM_UPGRADE.md](./PKM_UPGRADE.md).

### Key Features

**Domain Categorization:**
- Notes are automatically classified as Personal, Academic, Professional, or Creative
- Retrieval and chat synthesis adapt based on query domain
- Domain-specific boosting (1.5x) for relevant notes

**Academic Knowledge Graph:**
- Citation tracking with `CITES` relationships to papers, books, quotes
- Prerequisite chains with `PREREQUISITE_FOR` (e.g., Calculus → Linear Algebra)
- Contradiction detection with `CONTRADICTS` (e.g., Deterministic vs Stochastic)

**External References:**
- Track papers, books, videos, quotes with full attribution
- Automatic extraction from note content
- Linked to concepts in knowledge graph

**Cross-Domain Insights:**
- System connects personal experiences with academic learning
- Example: Links "anxiety about unpredictability" with "studying stochastic processes"

**Domain-Aware Synthesis:**
- Academic queries get pedagogical, concept-focused responses
- Personal queries get empathetic, insight-focused responses
- Professional queries get concise, action-focused responses
- Creative queries get thematic, imagery-rich reflections

### Example Use Cases

**Academic Learning:**
```
Input: "Markov Chains lecture - memoryless property"
Output:
  - Domain: Academic
  - Concepts: Markov Chain, Memoryless Property
  - Graph: Markov Chain -[PREREQUISITE_FOR]-> Probability Distributions
```

**Personal Journal:**
```
Input: "Feeling anxious about thesis defense"
Output:
  - Domain: Personal
  - Concepts: Anxiety
  - Persona: Anxious about unpredictability
  - Cross-link: Connects to "Stochastic Processes" concept
```

**Professional Documentation:**
```
Input: "Team meeting - decided to use GraphRAG architecture"
Output:
  - Domain: Professional
  - Entities: Team, GraphRAG
  - Tasks: Implement GraphRAG
```

### Implementation Details

**Schema Fix (Critical):** The LLM extraction requires both the Pydantic model AND the `system_msg` JSON template in `llm.py` to include `domain` and `references` fields. Without the template update, the LLM defaults to "Personal" for all notes.

**Domain Detection:** The system prioritizes content over writing style:
- "I learned about X" (first-person academic content) → Academic
- "We decided in meeting to use X" (first-person work content) → Professional  
- "I feel anxious about X" (emotional reflection) → Personal

**Migration Notes:**
- **Existing data:** All old notes default to "Personal" domain - no migration needed
- **New features:** Automatically available for new notes without breaking changes
- **Graph visualization:** Domain colors and Reference nodes appear immediately after backend restart

---

## 🎨 Customization

### Adding Custom Domains

LiveOS supports custom domain categories beyond the built-in Personal/Academic/Professional/Creative. To add a new domain:

**1. Backend Schema** ([app/schemas/extraction.py](backend/app/schemas/extraction.py#L71)):
```python
domain: str = "Personal"  # Add your domain to this comment
```

**2. Ingestion Prompt** ([app/workflows/agents/ingestion_agent.py](backend/app/workflows/agents/ingestion_agent.py#L151)):
```python
- "YourDomain": Description and examples
```

**3. LLM System Message** ([app/services/llm.py](backend/app/services/llm.py#L77)):
```python
"domain": "Academic|Personal|Professional|YourDomain"
```

**4. Retrieval Keywords** ([app/services/retrieval.py](backend/app/services/retrieval.py#L317)):
```python
yourdomain_keywords = ["keyword1", "keyword2", ...]
```

**5. Synthesis Mode** ([app/services/llm.py](backend/app/services/llm.py#L210)):
```python
elif query_domain == "YourDomain":
    domain_instructions = """..."""
```

**6. Frontend Graph Color** ([frontend/src/app/graph/page.tsx](frontend/src/app/graph/page.tsx#L157)):
```tsx
if (node.domain === "YourDomain") return "#hexcolor";
```

---

### Logging System (`backend/logs/`)

The backend uses a comprehensive file-based logging system with automatic rotation. All debug/info output goes to component-specific log files, while the console only shows warnings and errors.

**Log Files:**
- `ingestion.log` - Ingestion pipeline operations
- `retrieval.log` - Query processing and search
- `graph.log` - Neo4j operations
- `llm.log` - LLM service calls
- `api.log` - FastAPI endpoints
- `errors.log` - All ERROR+ messages across services

**Configuration:**
- 10MB max file size with 5 rotating backups
- DEBUG level in files, WARNING+ in console
- See [backend/logs/README.md](backend/logs/README.md) for viewing commands

---

---

## 📖 Additional Documentation

### Multi-Provider LLM Support

LiveOS supports multiple LLM providers beyond Ollama. See [MULTI_PROVIDER.md](MULTI_PROVIDER.md) for:
- **Provider comparison** (Ollama, OpenAI, Gemini, Anthropic)
- **Structured outputs** implementation across providers
- **Automatic fallback** configuration
- **Cost optimization** strategies
- **Migration guides** from single-provider setups

**Quick Start:**
```bash
# Switch to OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-proj-...
export OPENAI_MODEL=gpt-4o-2024-08-06

# With automatic fallback
export LLM_FALLBACK_PROVIDER=ollama
```

### Retrieval System Deep Dive

**Key Concepts:**
- **Neighborhood Summaries**: Each graph node (Concept, Entity, Task) maintains an incrementally updated summary that aggregates information across all notes that mention it
- **Graph-First Strategy**: Searches distilled knowledge nodes (25 max) before falling back to note-level vector search
- **Symbolic Ranking**: Pure priority-based scoring trusts graph structure over neural reranking (primary nodes = 100, secondary = 50)
- **Fact Pool Context**: Unified evidence format with semantic labels ([CORE CONSENSUS], [RELATED CONTEXT], [DOMAIN OVERVIEW])

**Testing the System:**
```bash
# Test retrieval with specific queries
cd backend
python -m pytest tests/test_vector_search.py -v

# Check retrieval logs
tail -f logs/retrieval.log
```

See [RETRIEVAL_FAQ.md](backend/RETRIEVAL_FAQ.md) for detailed explanations of:
- How neighborhood summaries work and update
- Graph-first retrieval architecture
- Multi-factor scoring formulas
- Dynamic cutoff strategies
- Performance optimization techniques

### Bi-Temporal Knowledge Tracking

LiveOS implements **bi-temporal data modeling** to accurately track both when facts became true and when they were recorded:

**Time Dimensions:**
- `valid_from`: **Event Time** - When the fact became true (note's `created_at` date)
- `ingested_at`: **System Time** - When the system recorded the fact (always `now()`)
- `valid_to`: When the fact stopped being true (null if still valid)
- `is_active`: Quick boolean filter for current relationships

**Use Case - Historical Note Ingestion:**
```
Note from 2024-01-15: "Started new job at Acme Corp"
→ valid_from: 2024-01-15 (when it happened)
→ ingested_at: 2026-01-31 (when you added it to LiveOS)
→ is_active: true (still true today)
```

**Soft Invalidation:**
When new information contradicts old facts, the system marks the old relationship as inactive instead of deleting it:
```
Old: "Chris works at Acme" (valid_from: 2024-01, is_active: false, valid_to: 2025-06)
New: "Chris works at Globex" (valid_from: 2025-06, is_active: true)
```

**Benefits:**
- Historical notes preserve their original dates when batch-ingested
- Query "as-of" any point in time (event time or system time)
- Full audit trail of knowledge evolution
- No data loss from corrections

### Community Summaries (GraphRAG)

LiveOS implements **Microsoft GraphRAG-style Community Summaries** for broad, exploratory queries:

**Domain-Based Communities:**
| Community | Description |
|-----------|-------------|
| Professional Knowledge | Work, career, projects, colleagues |
| Academic Knowledge | Learning, concepts, papers, courses |
| Personal Knowledge | Relationships, feelings, life events |
| Creative Knowledge | Art, writing, music, poetry |
| Dreams Knowledge | Dream journals, subconscious patterns |

**How It Works:**
1. **Ingestion**: Each extracted entity/concept is assigned to a Community based on detected domain
2. **Aggregation**: Communities track member nodes and generate high-level summaries
3. **Retrieval**: Broad queries (e.g., "summarize my work life") fetch Community summaries first

**Query Example:**
```
Query: "What are the major themes in my professional life?"
→ Retrieves: [Community - Professional: Professional Knowledge]
→ Summary: "Your professional journey centers on AI development, 
   startup culture, and technical leadership..."
```

**Graph Structure:**
```
(Entity: Chris) -[:BELONGS_TO]-> (Community: Professional Knowledge)
(Concept: GraphRAG) -[:BELONGS_TO]-> (Community: Academic Knowledge)
```

### Knowledge Graph Relationships

**Inter-Node Relationships** (extracted from note content):
- Social: `knows`, `friends_with`, `works_with`
- Hierarchy: `manages`, `reports_to`
- Dependencies: `prerequisite_for`, `depends_on`
- Conflicts: `contradicts`, `blocks`
- Similarities: `similar_to`, `related_to`
- Ownership: `assigned_to`, `created_by`

**Academic Relationships** (domain-specific):
- `PREREQUISITE_FOR`: Concept A builds on Concept B
- `CONTRADICTS`: Concept A opposes Concept B
- `CITES`: Note references external source

**Visualization:**
- 2D/3D graphs show color-coded relationship links
- Directional particles indicate flow (dependencies, prerequisites)
- Relationship types visible on hover

### Performance & Optimization

**Recent Optimizations:**
- **Retrieval Speed**: 70.75s → 67.34s (3.5% faster) with early stopping
- **Context Quality**: 36.8 → 28.2 results per query (23% token reduction)
- **Relevance**: Entity queries improved 10% → 50% (5× better precision)
- **Resource Usage**: PaddleOCR-VL saves 6GB VRAM vs DeepSeek-OCR

**Key Results:**
- **Symbolic Ranking**: Instant scoring (~0.0001s) vs neural reranking (~2.0s)
- **Conversational Synthesis**: "Thoughtful Peer" persona produces natural, grounded responses
- **Embedding Models**: Qwen3 0.6B provides 90%+ quality at 8× smaller size vs 8B models

---
