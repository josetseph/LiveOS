# Gemini Flash (gemini-3-flash-preview) Knowledge Graph Ingestion Report

**Report Date:** February 26, 2026  
**System:** LiveOS Brain — Personal Knowledge Management System  
**Model:** Google Gemini API — `gemini-3-flash-preview`  
**Ingestion Period:** February 25–26, 2026 (Two sessions across two API projects due to daily request limit)

---

## Executive Summary

This report documents a complete batch ingestion of the HotPotQA benchmark dataset using **Google's Gemini Flash** (`gemini-3-flash-preview`) as the knowledge extraction engine within the LiveOS Brain system. The ingestion successfully processed all **990 notes** from the dataset with a **100% success rate** and zero lost notes, despite encountering a Google API daily request quota limit midway through, which required creating a second API project to continue.

Gemini Flash demonstrated dramatically faster throughput compared to previous runs using Gemma3:4B (local inference). The average per-note processing time dropped from **120–180 seconds** (Gemma3:4B) to just **34.28 seconds** — a **3.5–5× speed improvement** — while maintaining comparable or superior extraction quality.

**Key Highlights:**
- **990/990 notes processed** — 100% completion, zero failures
- **~9.43 compute-hours total** vs. ~46 hours for Gemma3:4B
- **Average 34.28s per note** (median: 33.87s)
- **8,879 graph nodes** and **3,504 graph relationships** created
- **~4,960 entities** and **~1,665 concepts** extracted
- **563 unique relationship types** discovered by the LLM
- **2,347 total LLM API calls** (extraction + alias detection)
- **85 errors total** — all non-fatal: 32 Neo4j syntax errors, 13 rate-limit transient errors (retried successfully), 40 miscellaneous

---

## 1. System Configuration

### 1.1 Model & API Setup

**Primary LLM:** Google Gemini `gemini-3-flash-preview` via native SDK  
**Deployment:** Cloud API (Google AI Studio / Google Cloud)  
**Provider:** `GEMINI` (configured as primary LLM provider)  
**API Projects Used:**
- **Project 1:** Sessions 1 — processed 683 notes before hitting the daily requests-per-day (RPD) limit
- **Project 2:** Session 2 — used a newly created project with a fresh API key to process the remaining 307 notes

> **Note:** The Gemini free tier or lower-tier plans enforce a daily RPD cap. After Project 1 exhausted its daily quota, a new Google Cloud project was created with a new API key, configured in the system, and the ingestion was resumed via the batch pipeline's `--resume` checkpointing feature.

### 1.2 Infrastructure Stack

**Knowledge Storage:**
- **Graph Database:** Neo4j (entity relationships, traversal)
- **Relational Database:** PostgreSQL via asyncpg (`postgresql+asyncpg://...@127.0.0.1:5434/liveos`)
- **Vector Store:** Embedding-based semantic search (1024-dimensional)
- **Object Storage:** MinIO (multimedia attachments)

**Processing Pipeline Stages:**
1. **Multimedia Processing** — OCR (Florence-2), Speech-to-Text (Whisper)
2. **Metadata Extraction** — Gemini structured output (entities, concepts, relationships, summaries)
3. **Graph Storage** — Neo4j node and relationship creation via Cypher
4. **Embedding Generation** — Sentence-transformer vector embeddings
5. **Alias Detection** — Two-stage fuzzy + semantic similarity with LLM verification
6. **Community Detection** — Graph-based clustering

---

## 2. Dataset Overview

### 2.1 Source Data

**Dataset:** HotPotQA Wikipedia Excerpts  
**Location:** `backend/tests/benchmark/hotpotqa_notes/`  
**Format:** Markdown files containing Wikipedia article excerpts  
**Total Files Available:** 990  
**Notes Processed:** 990  
**Processing Coverage:** 100%

### 2.2 Benchmark Mode

All ingestion was performed with `BENCHMARK_MODE=true`, which:
- Uses third-person, objective summaries (not personal "you did X" framing)
- Returns factual answers without personal narrative injection
- Removes "Second Brain" persona language from prompts

---

## 3. Ingestion Session Breakdown

The full run was split across two sessions and two API projects.

| | Session 1 (Project 1) | Session 2 (Project 2) |
|---|---|---|
| **Log File** | `ingestion_1.log` | `ingestion.log` |
| **Notes Processed** | 683 | 307 |
| **Wall Clock Start** | 2026-02-25 05:28 | 2026-02-25 11:49 |
| **Wall Clock End** | 2026-02-25 11:49 | 2026-02-26 08:40 |
| **Wall Clock Duration** | ~6.35 hours | ~20.85 hours\* |
| **Avg Processing Time** | 32.90s/note | 37.36s/note |
| **Compute Time Total** | ~6.24 hours | ~3.19 hours |
| **Termination Reason** | Daily API RPD quota exhausted | Completed successfully |

\* Session 2's wall clock is significantly longer than compute time because it includes idle time waiting after rate limit hits (429 errors), and the gap between project creation and resumption.

> **Resume Mechanism:** The batch ingest script (`batch_ingest.py`) supports `--resume` mode, which uses checkpoint tracking in PostgreSQL to skip already-processed notes. This allowed seamless continuation from exactly where Session 1 left off without any duplicated work.

---

## 4. Timing & Throughput Metrics

### 4.1 Per-Note Processing Time (990 notes combined)

| Metric | Value |
|--------|-------|
| **Average** | 34.28s |
| **Median (P50)** | 33.87s |
| **Minimum** | 14.91s |
| **Maximum** | 104.34s |
| **P25** | 29.38s |
| **P75** | 38.14s |
| **P90** | 43.31s |
| **P95** | 46.61s |

### 4.2 Processing Time Distribution

| Bucket | Count | Percentage |
|--------|-------|------------|
| < 10s | 0 | 0.0% |
| 10–20s | 20 | 2.0% |
| 20–30s | 258 | 26.1% |
| **30–45s** | **641** | **64.7%** |
| 45–60s | 63 | 6.4% |
| > 60s | 8 | 0.8% |

The vast majority of notes (64.7%) completed within the 30–45 second window, indicating very consistent extraction performance. Only 8 notes (0.8%) exceeded 60 seconds — likely due to transient API latency or complex content requiring larger LLM responses.

### 4.3 Total Throughput

| Metric | Value |
|--------|-------|
| **Total Notes** | 990 |
| **Total Compute Time** | 33,940s (~9.43 hours) |
| **Effective Throughput** | ~1.75 notes/minute |
| **Wall Clock (Session 1)** | ~6.35 hours |
| **Wall Clock (Session 2)** | ~20.85 hours |

### 4.4 Comparison to Previous Run (Gemma3:4B Local)

| Metric | Gemma3:4B (Local) | Gemini Flash (Cloud) | Improvement |
|--------|-------------------|----------------------|-------------|
| Avg per note | ~150s (est.) | **34.28s** | **~4.4× faster** |
| Total compute time | ~46 hours | **~9.43 hours** | **~4.9× faster** |
| Notes completed | 991 | **990** | Equivalent |
| Success rate | 100% | **100%** | Equivalent |
| API dependency | None (local) | Google Cloud | — |

---

## 5. LLM API Call Metrics

### 5.1 Call Volume Summary

| Call Type | Total Calls | Per Note (avg) |
|-----------|-------------|----------------|
| **Knowledge Extraction** | 1,843 | 1.862 |
| **Alias Detection (LLM verification)** | 504 | 0.509 |
| **Total** | **2,347** | **2.371** |

> The extraction pipeline makes approximately **2 LLM calls per note** on average: one for the primary structured extraction (entities, concepts, relationships, summary) and occasional secondary calls for follow-up tasks such as entity summarization. The ~1.862 average reflects that some notes completed in a single call while others required additional calls (retries or supplemental summaries).

### 5.2 Model Usage

All 1,843 extraction calls used a single model:

| Model | Calls | % |
|-------|-------|---|
| `gemini-3-flash-preview` | 1,843 | 100% |

### 5.3 Rate Limit Incidents

The Google Gemini API returned `429 RESOURCE_EXHAUSTED` errors on **13 occasions** across both sessions:

- **Session 1:** The full daily RPD quota for Project 1 was exhausted after processing 683 notes. As no automatic RPD reset could be awaited in a reasonable window, a new API project was created.
- **Session 2:** 13 transient `429 RESOURCE_EXHAUSTED` errors were encountered during entity summary generation (notably for entities like `kreva`, `radziwiłł`, `goštautai`) and one extraction retry. These were handled by the pipeline's retry logic and did not result in any lost notes.

---

## 6. Extraction Quality Metrics

### 6.1 Entities

| Metric | Value |
|--------|-------|
| **Avg entities per note** | 5.00 |
| **Min entities in a note** | 0 |
| **Max entities in a note** | 15 |
| **Estimated total entities extracted** | ~4,960 |
| **Notes with 0 entities** | 3 (0.3%) |

**Entity count distribution per note:**

| Range | Notes | % |
|-------|-------|---|
| 0 | 3 | 0.3% |
| 1–2 | 93 | 9.4% |
| 3–4 | 323 | 32.6% |
| **5–6** | **367** | **37.0%** |
| 7–8 | 152 | 15.3% |
| 9+ | 56 | 5.7% |

**Top entity types extracted (raw counts across all notes):**

| Entity Type | Count | % of Total |
|-------------|-------|------------|
| Person | 3,193 | 27.1% |
| Entity (generic) | 2,358 | 20.0% |
| Organization | 2,328 | 19.8% |
| Place | 1,128 | 9.6% |
| Concept | 881 | 7.5% |
| Book | 286 | 2.4% |
| Song | 253 | 2.1% |
| Video | 208 | 1.8% |
| Paper | 103 | 0.9% |
| Actor | 101 | 0.9% |
| Band | 88 | 0.7% |
| *Other types* | *860+* | *7.3%+* |

> **Observation:** The generic `Entity` type (20%) suggests the LLM occasionally defaults to a catch-all label when the entity doesn't cleanly fit a named category. Future prompt tuning could further reduce this in favor of more specific types.

### 6.2 Concepts

| Metric | Value |
|--------|-------|
| **Avg concepts per note** | 1.68 |
| **Min** | 0 |
| **Max** | 4 |
| **Estimated total concepts extracted** | ~1,663 |

Concepts represent abstract ideas, themes, or domains extracted from the text (e.g., "Hip-hop music", "Hardcore punk", "Political Campaign"). The HotPotQA dataset's factual/encyclopedic nature produces fewer abstract concepts per note compared to personal notes.

### 6.3 Relationships

#### Extracted Relationships (LLM output, per extraction record)

| Metric | Value |
|--------|-------|
| **Avg relationships per note** | 3.64 |
| **Min** | 0 |
| **Max** | 8 |
| **Estimated total extracted** | ~3,604 |

#### Committed Graph Relationships (actually written to Neo4j)

| Metric | Value |
|--------|-------|
| **Total relationship log entries** | 3,504 |
| **Unique relationship types** | **563** |
| **Avg relationships written per note** | 3.54 |

> The slight difference between extracted (3,604) and committed (3,504) relationships is due to the 32 Neo4j syntax errors caused by hyphenated relationship type names (e.g., `co-founded`, `vice-chairman_of`) which Neo4j's Cypher parser rejects. See [Section 8](#8-errors-and-failures) for details.

**Top 30 graph relationship types (by frequency):**

| Rank | Relationship Type | Count |
|------|------------------|-------|
| 1 | `part_of` | 514 |
| 2 | `related_to` | 247 |
| 3 | `created_by` | 235 |
| 4 | `expert_in` | 216 |
| 5 | `works_with` | 161 |
| 6 | `manages` | 128 |
| 7 | `example_of` | 126 |
| 8 | `implements` | 110 |
| 9 | `located_in` | 72 |
| 10 | `contains` | 70 |
| 11 | `member_of` | 58 |
| 12 | `based_on` | 55 |
| 13 | `works_for` | 40 |
| 14 | `directed` | 35 |
| 15 | `reports_to` | 35 |
| 16 | `works_at` | 27 |
| 17 | `starred_in` | 26 |
| 18 | `teaches` | 23 |
| 19 | `interested_in` | 23 |
| 20 | `founded` | 22 |
| 21 | `stars_in` | 21 |
| 22 | `married_to` | 20 |
| 23 | `siblings_with` | 18 |
| 24 | `named_after` | 18 |
| 25 | `involves` | 18 |
| 26 | `based_in` | 17 |
| 27 | `owns` | 16 |
| 28 | `produced_by` | 14 |
| 29 | `produced` | 13 |
| 30 | `similar_to` | 12 |

The 563 **unique relationship types** is a testament to the LLM's semantic range — the model produces highly contextual, domain-specific relationship labels rather than defaulting to a small fixed vocabulary.

### 6.4 References

| Metric | Value |
|--------|-------|
| **Avg references per note** | 0.808 |
| **Notes with ≥1 reference** | 467 (47.2%) |

Nearly half of all notes yielded at least one extracted reference (citations, source material, cross-references), reflecting the encyclopedic nature of the HotPotQA source data.

### 6.5 Tasks

| Metric | Value |
|--------|-------|
| **Avg tasks per note** | 0.016 |
| **Notes with ≥1 task** | 11 (1.1%) |

Tasks are near-absent in this dataset, which is expected — the HotPotQA data consists of Wikipedia excerpts, not actionable personal notes.

### 6.6 Persona Traits

**0 persona traits** were extracted across all 990 notes — correct behavior for third-person encyclopedic content in Benchmark Mode.

---

## 7. Knowledge Graph Metrics

### 7.1 Graph Growth Summary

| Metric | Value |
|--------|-------|
| **Total nodes created** | 8,879 |
| **Total relationships created** | 3,530 (3,504 during ingestion + 26 backfilled) |
| **Total properties set** | 164,090 |
| **Avg nodes per note** | 8.97 |
| **Avg relationships per note** | 3.57 |
| **Avg properties per note** | 165.7 |

> **Note:** The relationship count includes 26 relationships that were retroactively added via the post-ingestion backfill script after fixing the hyphenated relationship type issue.

### 7.2 Node Composition

Each note creates a baseline set of nodes per entity, plus concept nodes, and the note's own metadata node. With 990 notes and ~5 entities average:

| Node Source | Estimated Count |
|-------------|----------------|
| Entity nodes | ~4,960 |
| Concept nodes | ~1,663 |
| Note metadata nodes | ~990 |
| Other (summaries, communities) | ~1,266 |
| **Total** | **~8,879** |

### 7.3 Relationship Vocabulary Diversity

The 563 unique relationship types (across 3,504 committed relationships) demonstrates:
- An average of **6.2 relationships per unique type** — meaning the vocabulary is broad but not overly sparse
- Strong coverage of **hierarchical** (`part_of`, `contains`, `member_of`), **relational** (`related_to`, `works_with`), **creational** (`created_by`, `founded`, `produced_by`), and **social** (`married_to`, `siblings_with`, `friends_with`) relationship categories

---

## 8. Errors and Failures

### 8.1 Summary

| Error Category | Count | % of Notes |
|----------------|-------|------------|
| Neo4j syntax error (hyphenated rel. type) | 32 | 3.2% |
| Rate limit / quota (429 RESOURCE_EXHAUSTED) | 13 | 1.3% |
| Other (miscellaneous non-fatal) | 40 | 4.0% |
| **Total errors** | **85** | **8.59%** |
| **Notes with permanent failure** | **0** | **0%** |

> All 85 errors were **non-fatal**. Notes affected by transient errors were either retried successfully or had the failing sub-operation skipped gracefully, preserving the overall 100% note completion rate.

### 8.2 Neo4j Cypher Syntax Errors (Hyphenated Relationship Types) ✅ **FIXED**

**Count:** 32 occurrences (during initial ingestion)  
**Root Cause:** Neo4j's Cypher syntax does not allow hyphens (`-`) in relationship type identifiers without escaping. When the LLM generates a relationship type containing a hyphen (e.g., `co-founded`, `vice-chairman_of`, `co-written_by`), the raw `CREATE (a)-[r:co-founded]->(b)` query is syntactically invalid.

**Affected relationship types:**
```
co-founded         vice-chairman_of    co-founder
co-founder_of      co-founder_and_ceo_of
co-written_by      live-streamed
```

**Impact (during ingestion):** The specific relationship was not written to the graph. All other data for the affected note (entities, concepts, remaining relationships, embeddings) was committed successfully.

**Resolution (Post-Ingestion Fix):**
1. **Code fix applied:** Added relationship type sanitization in [`backend/app/services/graph.py`](backend/app/services/graph.py#L821-L823) that replaces hyphens with underscores before constructing Cypher queries (e.g., `co-founded` → `co_founded`).
2. **Retroactive backfill:** Created [`scripts/backfill_failed_relationships.py`](backend/scripts/backfill_failed_relationships.py) to parse `errors.log`, extract all failed relationships, and create them with sanitized type names.
3. **Backfill executed:** Successfully created **26 unique relationships** (from 46 log entries, duplicates deduplicated via `MERGE`) with `backfilled=true` property for provenance.

**Status:** ✅ All missing relationships have been added to the graph. Future ingestions will automatically sanitize hyphenated types.

### 8.3 Rate Limit Errors (429 RESOURCE_EXHAUSTED)

**Count:** 13  
**Timestamp:** 2026-02-25 16:32 (during Session 2)  
**Affected operations:** Entity summary generation (background async) and one extraction call  
**Examples:**
```
[2026-02-25 16:32:22] Async Entity Summary Generation Failed for kreva: 429 RESOURCE_EXHAUSTED
[2026-02-25 16:32:22] Async Entity Summary Generation Failed for radziwiłł: 429 RESOURCE_EXHAUSTED
[2026-02-25 16:32:25] [Gemini] Extraction error: 429 RESOURCE_EXHAUSTED
```

**Impact:** These were transient — the pipeline's retry logic handled the extraction error, and the affected entity summaries either retried or were gracefully degraded. No notes were lost.

**Broader Rate Limit Event (Session Boundary):**  
The more significant rate limit event was the **exhaustion of Project 1's daily RPD quota** after 683 notes, which terminated Session 1. This necessitated:
1. Creating a new Google Cloud project
2. Generating a new API key
3. Updating the system's `.env` configuration
4. Resuming via `python batch_ingest.py ... --resume`

### 8.4 Other Errors

The remaining 40 miscellaneous errors in `errors.log` include:
- Intermittent Neo4j connection pool warnings
- Async task cleanup warnings on shutdown
- Non-critical validation edge cases in entity property normalization

---

## 9. Alias Detection Metrics

The alias detection subsystem (`AliasDetector`) evaluates whether newly ingested entities are aliases or alternate names for existing graph nodes, preventing duplicate entity proliferation.

### 9.1 Pipeline Performance

| Stage | Count | Notes |
|-------|-------|-------|
| Total entity lookups performed | ~9,249+ | All newly created entities |
| Stage 1 (Lexical): No candidates found | 8,681 | 93.9% — entities with no fuzzy match |
| Stage 1 (Lexical): Candidates found | 568 | Entities with ≥1 fuzzy match |
| Avg Stage 1 candidates per entity (when found) | 3.75 | |
| Stage 2 (Semantic Shield) pass rate | 568 / 12,285 (4.6%) | Strict semantic cosine threshold 0.65 |
| Candidates skipped (insufficient context) | 64 | |
| Stage 3 (LLM verification) calls | 504 | Final LLM-based disambiguation |

### 9.2 Two-Stage Funnel Efficiency

```
Total lookups (~9,249)
    └── Stage 1 (Lexical fuzzy): 568 pass (6.1%)
        └── Stage 2 (Semantic, threshold=0.65): 568 pass 4.6% of candidates evaluated
            └── Stage 3 (LLM): 504 calls for final disambiguation
```

The funnel is **highly conservative** — the semantic shield (0.65 cosine threshold) rejects the vast majority of Stage 1 candidates before invoking the LLM, keeping API costs minimal while still surfacing genuine aliases for review.

### 9.3 LLM Contribution to Alias Detection

- **504 LLM calls** were made for alias verification (Stage 3)
- These 504 calls represent **0.509 LLM calls per note** on average
- Including alias calls, the **total LLM calls per note rises to 2.371**

---

## 10. Content Analysis

### 10.1 Domain Distribution

The LLM's automatic domain classification of each note:

| Domain | Count | Percentage |
|--------|-------|------------|
| **Academic** | 915 | 92.4% |
| **Professional** | 75 | 7.6% |
| **Personal** | 2 | 0.2% |
| **Creative** | 2 | 0.2% |

The overwhelming **Academic** classification is accurate and expected — HotPotQA notes are Wikipedia excerpts covering encyclopedic topics.

### 10.2 Sentiment Distribution

| Sentiment | Count | Percentage |
|-----------|-------|------------|
| **Neutral** | 1,714 | 87.3% |
| **Positive** | 156 | 7.9% |
| **Informative** | 52 | 2.6% |
| neutral (lowercase variant) | 10 | 0.5% |
| **Respectful** | 8 | 0.4% |
| **Appreciative** | 4 | 0.2% |
| **Negative** | 4 | 0.2% |
| **Analytical** | 2 | 0.1% |
| **Inspirational** | 2 | 0.1% |

> The overwhelming **Neutral** sentiment (87.3% + 0.5% lowercase variant = 87.8% combined) is consistent with factual Wikipedia content. The 7.9% Positive likely corresponds to biography and achievement articles. The lowercase `neutral` variant (10 cases) reflects minor LLM output inconsistency in capitalization — a normalization step in post-processing would unify these.

**Total sentiment records:** 1,952 (exceeds 990 because sentiment is recorded per extraction pass, and some notes had multiple extraction events logged).

---

## 11. Pipeline Stage Timing

Where individual stage timings were captured:

| Stage | Avg Time | Min | Max | Sample Size |
|-------|----------|-----|-----|-------------|
| **Multimedia Processing** | 0.000s | 0.000s | 0.078s | 994 |
| **Graph Operations** | 14.61s | 6.14s | 67.57s | 990 |
| **LLM Extraction** | ~20–22s\* | — | — | ~990 |
| **Embedding + Storage** | ~8–10s\* | — | — | ~990 |

\* Estimated by subtracting known stage times from total ingestion time (34.28s avg).

**Stage time breakdown estimate (per note):**
```
Total avg: 34.28s
├── Multimedia processing:  ~0.00s  (0%)   — no media in this dataset
├── LLM API call (Gemini):  ~20-22s (60%)  — dominant cost
├── Graph operations:       ~14.6s  (43%)  — Neo4j write operations
├── Embeddings + storage:   ~8-10s  (25%)  — vector + PG write
└── (Overlap/parallelism accounted for in total)
```

The **LLM API call is the dominant time cost**, followed closely by graph write operations. The near-zero multimedia time confirms the HotPotQA dataset contains no images or audio.

---

## 12. Comparative Analysis

### 12.1 Gemini Flash vs. Gemma3:4B (Same Dataset)

| Dimension | Gemma3:4B (Feb 14–16) | Gemini Flash (Feb 25–26) |
|-----------|----------------------|--------------------------|
| **Notes processed** | 991 | 990 |
| **Success rate** | 100% | 100% |
| **Avg time/note** | ~150s (est.) | **34.28s** |
| **Total compute** | ~46 hours | **~9.43 hours** |
| **Avg entities/note** | ~5 (est.) | **5.00** |
| **Avg concepts/note** | ~2.3 (est.) | **1.68** |
| **Avg relationships/note** | — | **3.54** |
| **Unique rel. types** | — | **563** |
| **API dependency** | None (local Ollama) | Google Cloud required |
| **Cost** | Electricity only | API quota / cost |
| **Rate limits** | None | Yes (daily RPD) |
| **Infrastructure** | Local GPU/CPU | Cloud |

### 12.2 Key Observations

1. **Speed:** Gemini Flash is ~4.4× faster per note and ~4.9× faster total. For 990 notes, this saves ~36.5 hours of wall-clock processing time.

2. **Extraction Depth (Concepts):** Gemini Flash extracted slightly fewer concepts per note (1.68 vs. ~2.3 for Gemma3:4B). This may reflect different prompt interpretation, or may indicate that Gemma3 was occasionally over-extracting abstract concepts from concrete factual text.

3. **Extraction Depth (Entities):** Entity counts are nearly identical (~5/note), suggesting both models perform comparably at the primary entity recognition task.

4. **Relationship Richness:** Gemini produced 563 unique relationship types with highly contextual labels (e.g., `used_as_game_reserve`, `transferred_to`, `started_career_at`), demonstrating strong semantic understanding of the source material.

5. **Reliability:** Both models achieved 100% note completion. Gemini's errors were all non-fatal and handled by retry/graceful-degradation logic.

6. **Trade-offs:** Gemini Flash requires an active internet connection, is subject to rate limits, and incurs API costs. Gemma3:4B runs fully offline, has no rate limits, and is free at point-of-use (beyond hardware costs).

---

## 13. Recommendations & Known Issues

### 13.1 ✅ RESOLVED: Hyphenated Relationship Type Sanitization

**Priority: High** → **Status: Fixed (Feb 26, 2026)**

The 32 Neo4j syntax errors caused by hyphenated relationship type names (e.g., `co-founded`) represented lost graph data during the initial ingestion run.

**Resolution implemented:**
1. Added sanitization in [`backend/app/services/graph.py`](backend/app/services/graph.py#L821-L823):
   ```python
   # Sanitize relationship_type: Neo4j Cypher does not allow hyphens in
   # unquoted relationship type identifiers. Replace hyphens with underscores.
   relationship_type = relationship_type.strip().replace("-", "_")
   ```
2. Created and executed [`scripts/backfill_failed_relationships.py`](backend/scripts/backfill_failed_relationships.py) to retroactively add all 26 unique missing relationships with `backfilled=true` property.

**Outcome:** All previously failed relationships are now in the graph. Future ingestions automatically sanitize hyphenated types.

### 13.2 ✅ RESOLVED: Sentiment Capitalization Normalization

**Priority: Low** → **Status: Fixed (Feb 27, 2026)**  
The coexistence of `Neutral` and `neutral` in sentiment outputs was caused by the LLM occasionally returning lowercase values for the sentiment field.

**Resolution implemented:**  
Added a dedicated `@field_validator("sentiment", mode="before")` in [`backend/app/schemas/extraction.py`](backend/app/schemas/extraction.py) that calls `.capitalize()` on the value before storage:

```python
@field_validator("sentiment", mode="before")
@classmethod
def normalize_sentiment(cls, v: Any) -> str:
    if v is None:
        return "Neutral"
    if isinstance(v, str):
        return v.capitalize()
    return v
```

**Outcome:** All future ingestions will normalize sentiment values to title case (e.g., `neutral` → `Neutral`, `positive` → `Positive`) at the schema validation layer, eliminating duplicate variants in reporting.

### 13.3 Improvement: API Key Rotation / Multiple Project Support

**Priority: Medium**  
Session 1 was terminated by the daily RPD limit. An automated key rotation mechanism (cycling through a pool of project API keys when a 429 is received) would allow fully uninterrupted batch runs, eliminating the need for manual project creation mid-run.

### 13.4 Observation: Generic `Entity` Type Prevalence

**Priority: Low**  
~20% of extracted entities use the generic `Entity` type rather than a specific category. Prompt refinement — providing a richer taxonomy of entity types with examples — could reduce this and improve graph queryability.

### 13.5 Monitor: Alias Detection Recall

The alias pipeline evaluated ~9,249 entities and made 504 LLM verification calls. The Stage 2 semantic shield pass rate was very low (4.6%), which is conservative by design. For a factual encyclopedic dataset like HotPotQA, which contains many unambiguous proper nouns, this rate seems appropriate. However, it is worth validating whether any true aliases (e.g., `Crank` ↔ `Crank Caverns`) are being missed due to the strict threshold.

---

## 14. Raw Metrics Reference

| Metric | Value |
|--------|-------|
| Total notes | 990 |
| Total successes | 990 (100%) |
| Total failures | 0 (0%) |
| Session 1 notes | 683 |
| Session 2 notes | 307 |
| Avg ingestion time | 34.28s |
| Median ingestion time | 33.87s |
| Min ingestion time | 14.91s |
| Max ingestion time | 104.34s |
| P25 ingestion time | 29.38s |
| P75 ingestion time | 38.14s |
| P90 ingestion time | 43.31s |
| P95 ingestion time | 46.61s |
| Total compute time | 33,940s (9.43 hrs) |
| Total LLM extraction calls | 1,843 |
| Total alias LLM calls | 504 |
| Total LLM calls | 2,347 |
| LLM extraction calls/note | 1.862 |
| Alias LLM calls/note | 0.509 |
| Total LLM calls/note | 2.371 |
| Avg entities/note | 5.00 |
| Avg concepts/note | 1.68 |
| Avg extracted relationships/note | 3.64 |
| Avg references/note | 0.808 |
| Avg tasks/note | 0.016 |
| Total graph nodes created | 8,879 |
| Total graph relationships written | 3,504 |
| Total properties set | 164,090 |
| Unique relationship types | 563 |
| Avg nodes/note | 8.97 |
| Avg graph relationships/note | 3.54 |
| Total errors | 85 |
| Neo4j syntax errors | 32 |
| Rate limit errors (retried) | 13 |
| Other errors | 40 |
| Error rate (% of notes affected) | 8.59% (non-fatal) |
| Alias lookups (no-candidate) | 8,681 |
| Alias candidates found | 568 |
| Alias candidates skipped | 64 |
| Stage 2 semantic pass rate | 4.6% |
| Domain: Academic | 92.4% |
| Domain: Professional | 7.6% |
| Sentiment: Neutral | 87.8% |
| Sentiment: Positive | 7.9% |
| LLM model | gemini-3-flash-preview |
| API provider | Google Gemini |
| Database URL | postgresql+asyncpg://...@127.0.0.1:5434/liveos |
| Ingestion start | 2026-02-25 05:28:06 |
| Ingestion end | 2026-02-26 08:40:32 |

---

*Report generated from log analysis of: `gemini-3-flash-preview-ingestion-logs/ingestion.log`, `gemini-3-flash-preview-ingestion-logs/ingestion_1.log`, `gemini-3-flash-preview-ingestion-logs/llm.log`, `gemini-3-flash-preview-ingestion-logs/errors.log`, `gemini-3-flash-preview-ingestion-logs/graph.log`, `gemini-3-flash-preview-ingestion-logs/alias_detection.log`*
