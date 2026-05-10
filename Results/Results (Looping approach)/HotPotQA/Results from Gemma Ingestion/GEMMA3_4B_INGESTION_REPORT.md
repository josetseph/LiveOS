# Gemma3:4b Ingestion Report — HotPotQA (990 Notes) · Looping Approach

**Date Range:** March 7, 2026 15:30 → March 11, 2026 04:26  
**Model:** `gemma3:4b`  
**Infrastructure:** Ollama (http://localhost:11434/v1) — single provider throughout  
**Embedding:** `qwen3-embedding:0.6b` via Ollama  
**Dataset:** HotPotQA benchmark — 990 target notes across multiple sessions  
**Pipeline Variant:** "Looping Approach" — LangGraph 5-node state machine with high-frequency refinement

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Run Overview](#2-run-overview)
3. [Throughput & Timing](#3-throughput--timing)
4. [Pipeline Stage Breakdown](#4-pipeline-stage-breakdown)
5. [LLM Call Metrics](#5-llm-call-metrics)
6. [Refinement Node Analysis](#6-refinement-node-analysis)
7. [Knowledge Extraction Quality](#7-knowledge-extraction-quality)
8. [Knowledge Graph Output](#8-knowledge-graph-output)
9. [Community Clustering](#9-community-clustering)
10. [Error Analysis](#10-error-analysis)
11. [Pipeline Architecture Changes](#11-pipeline-architecture-changes)
12. [Key Observations & Bottlenecks](#12-key-observations--bottlenecks)

---

## 1. Executive Summary

All **990 HotPotQA notes** were successfully ingested with a **100% success rate**, processed across multiple sessions spanning March 7–11, 2026 (84.9 hours wall-clock / 3.54 days). `gemma3:4b` served as the extraction and summarization backbone via Ollama throughout.

The run introduced the **"Looping Approach"** pipeline — a LangGraph 5-node state machine with an active refinement loop that fired on **91.9% of notes** (910/990), adding 1,543 additional entities across 654 refinement patches. The result is a substantially richer per-note extraction compared to prior runs.

The extraction produced **11,216 graph nodes** and **15,386 relationships**, with knowledge distributed across **939 per-note topic communities** (45 merges) averaging 12.8 nodes each.

The dominant cost center remains **entity summarization**, which consumed 74.5% of total pipeline compute time (avg 199.45s/note). End-to-end latency averaged 268s/note (4.5 min/note) — significantly slower than earlier runs, largely due to the added refinement pass and the heavier per-note summarization workload driven by the richer extractions. All LLM timeouts were retried automatically with zero note-level failures.

**Key differences from previous runs:**
- Alias detection fully removed (reduced background noise, eliminated IS_SAME_AS overhead)
- Per-note LLM topic clustering replaces Louvain community detection
- Single provider throughout (Ollama only — no mid-run LM Studio switch)
- High refinement rate (91.9%) reflects the complex HotPotQA content triggering the ≥5 entity/concept threshold

---

## 2. Run Overview

| Metric | Value |
|---|---|
| **Notes targeted** | 990 |
| **Total ingestion starts** | 990 |
| **Successful ingestions** | 990 |
| **Success rate** | **100%** |
| **Failed / incomplete** | 0 |
| **Sessions** | 2 (ingestion_1.log: 779 starts, ingestion.log: 211 starts) |
| **Wall-clock start** | 2026-03-07 15:30:49 |
| **Wall-clock end** | 2026-03-11 04:26:18 |
| **Total wall-clock elapsed** | 84.92 hours (305,729 seconds / 3.54 days) |
| **Total compute time (sum of pipeline durations)** | 73.57 hours (264,866 seconds) |
| **Average time per note** | 267.5 seconds (4.5 min) |
| **Throughput** | **13.5 notes / hour** |
| **LLM provider** | Ollama · `gemma3:4b` |
| **Embedding provider** | Ollama · `qwen3-embedding:0.6b` |

> **On the 11.4-hour gap between compute and wall-clock time:** The run spanned 3.54 calendar days across 2 sessions. The gap between summed pipeline compute (73.57h) and wall-clock (84.92h) reflects idle intervals between sessions (server restarts, overnight pauses, and queuing overhead between notes). The pipeline processes notes sequentially.

---

## 3. Throughput & Timing

### 3.1 End-to-End Per-Note Duration

Full time from pipeline start to success confirmation, encompassing all stages.

| Statistic | Time (seconds) |
|---|---|
| **Count** | 990 |
| **Average** | **267.54s** |
| **Median** | 212.81s |
| **Std Dev** | ±244.83s |
| **Minimum** | 18.95s |
| **Maximum** | 2,495.01s |
| **P25** | 140.00s |
| **P75** | 292.86s |
| **P90** | 406.71s |
| **P95** | 814.92s |
| **Total compute** | 264,866s (73.57 hours) |

The large standard deviation (±253s) and extreme P95 (926s) indicate a long tail driven by LLM timeout-retry events and notes with exceptionally large extraction outputs. The median (208s) is a better typical-case estimate than the mean.

### 3.2 Throughput Summary

| Metric | Value |
|---|---|
| **Effective throughput** | 13.5 notes/hour |
| **Median time per note** | 3.5 minutes |
| **Mean time per note** | 4.5 minutes |

The 13.5 notes/hour throughput is lower than the preceding run (19.6 notes/hr). The regression is caused by: (1) the additional refinement LLM pass on 91.9% of notes, and (2) richer extractions increasing summarization workload.

---

## 4. Pipeline Stage Breakdown

The LangGraph pipeline processes each note through 5 sequential nodes: **multimodal → extraction → refinement (conditional) → storage → summarization**.

### 4.1 Stage Timing Summary

| Stage | Count | Avg (s) | Median (s) | Max (s) | Total (s) | % of Pipeline |
|---|---|---|---|---|---|---|
| **Extraction (LLM)** | 990 | 52.16 | 38.76 | 902.95 | 51,642 | **19.5%** |
| **Summarization (LLM)** | 990 | 199.45 | 152.04 | 1,561.35 | 197,453 | **74.5%** |
| **Graph Storage (Neo4j)** | 990 | 10.27 | 8.85 | 80.98 | 10,170 | **3.8%** |
| **Multimedia Processing** | 990 | 0.00035s | — | — | ~0.3 | **~0.0%** |
| **Other / overhead** | — | — | — | — | ~5,602 | **~2.1%** |

> **Note:** Refinement stage timing is not captured separately in `[Perf]` log lines. Refinement LLM calls are implicitly included within the "Extraction" stage total (the extraction node orchestrates both the initial call and any refinement retry calls). The reported extraction figure therefore captures extraction + refinement combined.

### 4.2 Stage Cost Proportions

```
Summarization  ████████████████████████████████████████████████████████████  74.5%
Extraction     ███████████████▌                                              19.5%
Graph Storage  ███                                                            3.8%
Other          █▋                                                             2.1%
```

**Summarization is the dominant bottleneck at 74.5% of total compute.** Summarization generates natural-language descriptions for every extracted entity, concept, and the note itself, driving 199s avg per note. This is an 83% increase over the prior run's 108.76s/note — because the richer extractions (8.5 entities/note vs 4.88/note previously) produce more entities that each require an individual summarization LLM call.

### 4.3 Extraction vs Summarization Trade-off

The extraction stage average (54.97s) includes refinement retry calls for the 91.8% of notes where refinement fired. Without refinement, the extraction call alone is estimated at ~39s (consistent with runs where refinement was off).

| Comparison | This Run | Previous Run |
|---|---|---|
| Extraction avg | 52.16s | 38.66s |
| Summarization avg | 199.45s | 108.76s |
| Entities extracted (avg/note) | 8.5 | 4.88 |
| Refinement rate | 91.9% | not in prev run |

The correlation is clear: more entities extracted → more summarization calls → more total time.

---

## 5. LLM Call Metrics

| Metric | Value |
|---|---|
| **LLM provider** | Ollama |
| **Extraction model** | `gemma3:4b` |
| **Embedding model** | `qwen3-embedding:0.6b` |
| **Total extraction LLM calls (logged)** | ~2,400 |
| **Avg extraction calls per note** | ~2.4 |
| **LLM timeouts (auto-retried)** | 100+ |
| **Sessions** | 2 (ingestion_1.log + ingestion.log) |

The ~2.4 avg LLM calls/note (vs 1.0 in a no-refinement scenario) breaks down as:
- ~990 initial extraction calls (1.0 per note)
- ~1,410 refinement calls on triggered notes (average ~1.6 refinement attempts per triggered note)

Because refinement triggered on 91.9% of notes, most notes received at least two LLM extraction calls. All timeouts were recovered via the retry mechanism, contributing to the high max pipeline duration (2,495s).

**Summarization** also uses `gemma3:4b` but calls are logged via "Summarization took:" timers rather than individual call lines. The 990 summarization stages are estimated to involve multiple LLM calls each (one per entity + one per concept + one note-level summary), totalling an estimated 990 × (8.5 + 2.7 + 1) ≈ **12,100+ summarization LLM calls** across the full run.

---

## 6. Refinement Node Analysis

The refinement node fires when the initial extraction produces ≥5 combined entities + concepts, triggering a second-pass "reasoning" LLM call to catch missed entities. This threshold was met by the majority of HotPotQA notes.

| Metric | Value |
|---|---|
| **Notes with refinement triggered** | 910 / 990 **(91.9%)** |
| **Notes without refinement** | 80 (8.1%) |
| **Refinement patches applied** | 654 |
| **Patch rate (of triggered)** | 654 / 910 = **71.9%** |
| **Total new entities added** | 1,543 |
| **Avg entities added per patch** | 2.4 |

Of the 910 notes where refinement was triggered, 654 actually produced patched extractions — 256 triggers found nothing to add. This 71.9% patch rate indicates the refinement pass is genuinely productive for nearly 3 in 4 triggered notes. The 1,543 additional entities represent an **18.4% increase** over the raw extraction baseline of 8,385 entities.

---

## 7. Knowledge Extraction Quality

### 7.1 Per-Note Extraction Stats

| Metric | Entities | Concepts |
|---|---|---|
| **Average per note** | 8.5 | 2.7 |
| **Median per note** | 8.0 | 3.0 |
| **Maximum** | 36 | 7 |
| **Total (raw extraction)** | 8,385 | 2,666 |
| **Added by refinement** | +1,543 | — |
| **Estimated total entities stored** | ~9,928 | 2,666 |

> Note: The "total entities stored" estimate adds raw extraction entities (8,385) plus refinement patches (1,543). The actual number of unique entity nodes in the graph (11,216 total nodes of all types) reflects merging of duplicate entity names across notes.

### 7.2 Comparison to Previous Run

| Metric | This Run (Looping) | Previous Run (990 notes) |
|---|---|---|
| Avg entities/note | **8.5** | 4.88 |
| Avg concepts/note | **2.7** | 2.30 |
| Total entities (estimated stored) | **~9,928** | 4,941 |
| Graph nodes | **11,216** | 9,024 |
| Graph relationships | **15,386** | 10,499 |

The Looping Approach extracts 74% more entities per note on average — the refinement pass and BENCHMARK_MODE encyclopedic prompt are both contributing. This translates directly into a richer and more connected knowledge graph.

---

## 8. Knowledge Graph Output

### 8.1 Summary

| Metric | Value |
|---|---|
| **Total nodes created** | 11,216 |
| **Total relationships created** | 15,386 |
| **Total properties set** | 181,462 |
| **Avg relationships per note** | 19.8 |

### 8.2 Top Relationship Types

The following relationship types were created most frequently (from graph creation log lines):

| Relationship | Count | % of Total Logged |
|---|---|---|
| `located_in` | 167 | 10.9% |
| `member_of` | 96 | 6.3% |
| `part_of` | 76 | 5.0% |
| `led` | 31 | 2.0% |
| `created` | 28 | 1.8% |
| `worked_for` | 23 | 1.5% |
| `released` | 21 | 1.4% |
| `born_in` | 18 | 1.2% |
| `won` | 18 | 1.2% |
| `participated_in` | 17 | 1.1% |
| `produced` | 17 | 1.1% |
| `competed_in` | 16 | 1.0% |
| `represented` | 15 | 1.0% |
| `owned` | 14 | 0.9% |
| `authored` | 14 | 0.9% |
| `includes` | 14 | 0.9% |
| `father_of` | 13 | 0.9% |
| `founded` | 13 | 0.9% |
| `borders` | 13 | 0.9% |
| `played_for` | 12 | 0.8% |

The prevalence of spatial (`located_in`, `borders`), organizational (`member_of`, `part_of`, `worked_for`, `represented`), and biographical (`born_in`, `father_of`) relationship types reflects the encyclopedic nature of HotPotQA content (geographic entities, historical figures, institutions).

> **Note on relationship type failures:** 32 Neo4j syntax errors originated from relationship types containing hyphens (e.g., `co-founded`, `official breakup`). These were logged as errors but the affected notes still completed successfully — the system skipped the malformed relationship and continued with the rest of the extraction.

---

## 9. Community Clustering

This run uses the **per-note LLM topic clustering** approach, replacing the Louvain algorithm used in prior runs.

### How It Works

For each ingested note, the pipeline:
1. Prompts `gemma3:4b` to generate a topic label for the note's content
2. Embeds that label with `qwen3-embedding:0.6b`
3. Searches existing community embeddings for similarity ≥ 0.75
4. Merges into an existing community if found, or creates a new one

### Community Stats

| Metric | Value |
|---|---|
| **Communities created** | 939 |
| **Community merges** | 45 |
| **Total node assignments** | 12,594 |
| **Avg nodes per community** | 12.8 |
| **Median nodes per community** | 12.0 |
| **Max nodes per community** | 41 |
| **Notes processed** | 990 |

With 45 merges across 939 communities, roughly 4.6% of notes found an existing community to merge into — much higher than the partial-run figure of 2. This suggests the longer run allowed enough topic overlap to start clustering (e.g., both the 28th and 32nd Independent Spirit Awards merged into a single community). Still, the 0.75 threshold remains strict; lowering to 0.60–0.65 would likely yield substantially more cross-note grouping.

**Sample community names generated:**
- "Crank Caverns: A Mining & History Site..."
- "DC Comics Superhero Roy Harper – Arsenal..."
- "Nick Powell: Professional Footballer..."
- "Lionel Train Command Control Systems..."
- "Kenton Richardson: Hartlepool United Football..."

The LLM-generated community names accurately reflect note content and provide human-readable cluster labels for retrieval filtering.

---

## 10. Error Analysis

### 10.1 Summary

All 990 notes completed successfully (100% success rate). Errors logged are non-fatal recoverable events.

| Error Type | Count | Impact |
|---|---|---|
| **LLM request timeouts** | 100 | Retried automatically — 0 note failures |
| **Neo4j syntax errors** (hyphenated rel types) | 32 | Individual relationship skipped — note succeeds |
| **JSON parse errors** (unterminated strings) | 39 | Affected extraction retried — note succeeds |
| **Other / relationship skips** | ~10 | Non-fatal, logged and skipped |
| **Note-level failures** | **0** | — |

### 10.2 Error Details

**LLM Timeouts (100 occurrences):** All requests that timed out were automatically retried. Timeouts are the primary driver of the extreme P95/max pipeline durations. Under high Ollama load (local machine), response times can spike sharply. No note failed due to timeouts.

**Neo4j Syntax Errors (32 occurrences):** The Cypher query builder does not escape relationship types containing hyphens or spaces. Examples: `co-founded`, `official breakup`, `released album`. When gemma3:4b generates these as relationship types, the Cypher query fails with `Invalid input '-'`. The system logs the error and continues without that specific relationship. Affected entity nodes are still created.

**JSON Parse Errors (39 occurrences):** Gemma3:4b occasionally generates truncated JSON responses (unterminated strings) when output length approaches the model's response limit. The pipeline catches these and retries, typically succeeding on the second attempt.

### 10.3 Alias Detection

The alias detection system was **fully removed** prior to this run. `alias_detection.log` is 0 bytes, confirming no alias detection activity occurred. This eliminates:
- Background async tasks after every node summary update
- IS_SAME_AS link generation (which added graph noise in prior runs)
- The 9,122 entity lookups + 607 LLM calls for disambiguation that appeared in the previous run

---

## 11. Pipeline Architecture Changes

This run reflects several significant architectural changes from the prior HotPotQA ingestion (990 notes, February 2026).

### 11.1 Changes in This Run

| Component | Previous State | This Run |
|---|---|---|
| **Alias detection** | Active: background async tasks, 607 LLM calls, 65 IS_SAME_AS links | **Removed entirely** |
| **Community detection** | Louvain graph algorithm (batch, offline) | **Per-note LLM topic clustering** (online, at ingestion time) |
| **LLM provider** | Ollama → LM Studio (MLX, mid-run switch) | **Ollama only**, single provider throughout |
| **Embedding** | MLX (Apple Silicon) via LM Studio | **qwen3-embedding:0.6b via Ollama** |
| **Refinement loop** | Not present | **Active: fires on ≥5 entities+concepts (91.8% of notes)** |
| **Retrieval (hybrid_search)** | 1-hop + 2-hop neighbor expansion | **Removed — entity name matching + vector search only** |
| **Retrieval (agentic loop)** | Single-pass retrieval | **Multi-pass self-correction (`retrieve_with_self_correction`)** |

### 11.2 Impact Assessment

| Change | Observed Impact |
|---|---|
| Alias removal | Eliminated 607+ background LLM calls; no IS_SAME_AS links in graph |
| Per-note community clustering | 745 communities created, only 2 merges — high diversity prevents clustering |
| Refinement loop | +1,195 entities (18.3% more than raw extraction); +16s avg extraction time |
| qwen3-embedding:0.6b | Smaller, faster embedding model; impact on retrieval quality TBD |
| Neighbor expansion removal | Retrieval precision expected to increase (fewer irrelevant nodes in context) |

---

## 12. Key Observations & Bottlenecks

### 12.1 Summarization Dominates at Scale

Summarization consumed **74.5%** of all pipeline compute (197,453s). At the extracted entity rate of 8.5 entities/note, the summarization node calls the LLM ~12 times per note (one per entity + concept + note level). Reducing summarization overhead — via batching, a smaller summarizer model, or summarizing only high-confidence entities — would be the highest-leverage optimization available.

### 12.2 Refinement Fires Near-Universally

The 91.9% refinement triggering rate suggests the ≥5 entity+concept threshold is too low for encyclopedic HotPotQA content. Almost every note exceeds this threshold. The refinement node is effectively unconditional on this dataset. Two options to consider:
- **Raise the threshold** (e.g., ≥8) to reduce refinement to truly borderline notes
- **Keep it as-is** — the 71.9% patch rate confirms it adds genuine value even if it fires broadly

### 12.3 Community Clustering: Better Than Partial Run Suggested

With 45 merges across 939 communities (~4.6% merge rate), the full run shows meaningfully more cross-note topic clustering than the partial run's 2/745 figure. The Independent Spirit Awards example in the logs shows the system correctly merging related ceremony notes. Still, 0.75 cosine similarity is strict — lowering to 0.60–0.65 would likely yield significantly more clustering across the 990-note corpus.

### 12.4 Hyphenated Relationship Types Need Escaping

32 graph errors stem from hyphens in LLM-generated relationship type names (e.g., `co-founded`). The Cypher query builder should sanitize relationship types before embedding them into the query — replacing hyphens with underscores or wrapping in backtick escaping. This is a simple fix that would eliminate 32 logged errors per similar-scale run.

### 12.5 LLM Timeouts Under Local Load

100+ timeouts across ~2,400 extraction LLM calls (~4–5% timeout rate). Under local Ollama inference, resource spikes cause occasional response failures. These were all recovered, but each timeout adds substantial latency to affected notes (often 200–900 extra seconds when restarted from scratch). Implementing a smarter retry — e.g., exponential backoff with partial result caching — would reduce worst-case note latency.

### 12.6 Knowledge Graph Richness vs. Previous Run

| Metric | Looping (990 notes) | Prior (990 notes) | Notes |
|---|---|---|---|
| Nodes | 11,216 | 9,024 | +24% |
| Relationships | 15,386 | 10,499 | +47% |
| Entities/note | 8.5 | 4.88 | +74% |
| Concepts/note | 2.7 | 2.30 | +17% |

The Looping Approach produces a meaningfully richer knowledge graph per note. Whether this translates to better retrieval and QA performance will be validated in subsequent benchmarks.

---

*Report generated from log files in `gemma3-4b-ingestion-logs/`. All metrics are combined across both session logs. Log line counts: ingestion_1.log (52,746 lines, session 1: 779 notes), ingestion.log (14,657 lines, session 2: 211 notes), graph.log (21,511), llm.log (3,993), errors.log (475), api.log (998). Alias detection log: 0 bytes (system removed).*
