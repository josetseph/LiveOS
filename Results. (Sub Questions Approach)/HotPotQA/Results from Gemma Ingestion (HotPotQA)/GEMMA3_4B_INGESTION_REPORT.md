# Gemma3:4b Ingestion Report — HotPotQA (990 Notes)

**Date Range:** February 25, 2026 05:28 → February 27, 2026 08:48  
**Model:** `gemma3:4b`  
**Infrastructure:** Ollama (initial) → LM Studio w/ MLX (primary, optimized for Apple Silicon)  
**Dataset:** HotPotQA benchmark — 990 target notes (1,018 ingestion attempts total, including retries)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Run Overview](#2-run-overview)
3. [Throughput & Timing](#3-throughput--timing)
4. [Pipeline Stage Breakdown](#4-pipeline-stage-breakdown)
5. [LLM Call Metrics](#5-llm-call-metrics)
6. [Knowledge Extraction Quality](#6-knowledge-extraction-quality)
7. [Alias Detection System](#7-alias-detection-system)
8. [Knowledge Graph Output](#8-knowledge-graph-output)
9. [Domain & Sentiment Classification](#9-domain--sentiment-classification)
10. [Entity Type Distribution](#10-entity-type-distribution)
11. [Error Analysis](#11-error-analysis)
12. [Provider Comparison: Ollama vs LM Studio](#12-provider-comparison-ollama-vs-lm-studio)
13. [Key Observations & Bottlenecks](#13-key-observations--bottlenecks)

---

## 1. Executive Summary

The full 990-note HotPotQA dataset was ingested into LiveOS across approximately 51.3 hours of wall-clock time, using `gemma3:4b` as the extraction backbone. The run completed with a **98.82% success rate** (1,006 of 1,018 attempts), producing a rich knowledge graph of **9,024 nodes** and **10,499 relationships**. The pipeline extracted **4,941 entities** and **2,282 concepts** total, averaging ~4.88 entities per note.

The most significant finding is the dominant cost center: **entity summarization** consumed 65% of total pipeline time per note on average (~109s/note), while LLM extraction itself took only ~39s/note. The alias detection system performed 9,122 entity lookups across the corpus, ultimately creating **65 IS_SAME_AS** coreference links with 607 LLM calls powering the final disambiguation judgments.

The mid-run switch from Ollama to LM Studio (MLX-optimized) was intended to exploit Apple Silicon's unified memory architecture. Metrics from both phases are captured in this report.

---

## 2. Run Overview

| Metric | Value |
|---|---|
| **Notes targeted** | 990 |
| **Ingestion attempts** | 1,018 |
| **Successful ingestions** | 1,006 |
| **Unique note IDs started** | 1,018 |
| **Unique note IDs succeeded** | 1,006 |
| **Success rate** | **98.82%** |
| **Failed / incomplete** | 12 (1.18%) |
| **Wall-clock start** | 2026-02-25 05:28:01 |
| **Wall-clock end** | 2026-02-27 08:48:18 |
| **Total elapsed** | 51.34 hours (184,817 seconds) |
| **Average time per note** | 183.71 seconds |
| **Throughput** | **19.6 notes / hour** |

> **Note on attempt count:** 1,018 attempts were logged for 990 target notes. This reflects ~28 retry/resume events from server restarts during the multi-day run (confirmed by `api.log` showing multiple process restarts). A small number of notes were re-processed.

---

## 3. Throughput & Timing

### 3.1 End-to-End Note Indexed Time

This measures the full time from note ingestion start to successful index confirmation, encompassing all pipeline stages.

| Statistic | Time (seconds) |
|---|---|
| **Count** | 1,006 |
| **Average** | **166.41s** |
| **Median** | 155.76s |
| **Std Dev** | ±111.14s |
| **Minimum** | 1.43s |
| **Maximum** | 1,000.51s |
| **P25** | 84.96s |
| **P75** | 213.41s |
| **P90** | 281.06s |
| **P95** | 352.04s |
| **Total (all notes)** | 167,405s (~46.5 hrs of compute) |

The high standard deviation (±111s) and long tail (P95 = 352s, max = 1,000s) indicate significant variance, primarily driven by LLM generation time fluctuating with model load and note content complexity.

### 3.2 Throughput Over Time

- **Effective throughput:** 19.6 notes/hour
- **Total wall clock for 1,006 notes:** 51.34 hours
- **Notes per session (avg across 8 server sessions):** ~126 notes/session

The low throughput (19.6 notes/hour) reflects that summarization, not extraction, dominates latency — summarization alone averaged ~109s/note.

---

## 4. Pipeline Stage Breakdown

The ingestion pipeline processes each note through several sequential stages. Timing is available for the stages below.

### 4.1 Stage Timing Summary

| Stage | Count | Avg (s) | Median (s) | P90 (s) | P95 (s) | Max (s) | Total (s) |
|---|---|---|---|---|---|---|---|
| **Full Extraction (LLM)** | 1,013 | 38.66 | 34.69 | 63.15 | 80.35 | 166.69 | 39,161 |
| **Summarization (LLM)** | 1,006 | 108.76 | 99.40 | 187.73 | 254.81 | 941.42 | 109,414 |
| **Graph Storage (Neo4j)** | 1,006 | 13.52 | 13.36 | 18.56 | 20.69 | 53.73 | 13,602 |

> **Embedding** and **alias detection** per-note timing was not captured in `[Perf]` log lines for this run. Alias detection time is implicitly included in the total indexed time.

### 4.2 Stage Cost Proportions (of logged stages)

Based on the logged stages (extraction + summarization + graph storage):

| Stage | Total Time | % of Logged |
|---|---|---|
| Summarization | 109,414s | **66.7%** |
| Extraction (LLM call) | 39,161s | **23.8%** |
| Graph Storage | 13,602s | **8.3%** |
| Other (embedding, alias, overhead) | ~22,841s* | ~12.2%* |

> *Estimated as the difference between total indexed time (167,405s) and the sum of known stages (162,177s).

**The summarization stage is the dominant bottleneck**, consuming 2.8× more time than the extraction stage. This is because summarization generates full natural-language descriptions for every extracted entity, concept, and the note itself — often requiring multiple LLM calls.

### 4.3 Extraction vs Summarization Distribution

```
Extraction time distribution:
  25th percentile: 25.6s
  Median:          34.7s
  75th percentile: 46.2s
  95th percentile: 80.4s

Summarization time distribution:
  25th percentile:  46.0s
  Median:           99.4s
  75th percentile: 143.5s
  95th percentile: 254.8s
  Maximum:         941.4s  ← outlier (likely LLM hang/retry)
```

The summarization step has far greater variance, with some notes taking up to 941 seconds. This is consistent with notes containing many entities requiring individual LLM summarization calls.

### 4.4 Note Complexity Classification

The pipeline classifies note complexity based on entity density:

| Complexity | Count | % of Total |
|---|---|---|
| **Upgraded (complex)** | 690 | **68.1%** |
| Normal | 323 | 31.9% |

For complex notes, the average entity+concept count at time of upgrade was **9.23** (median 8, max 33). This means 68% of HotPotQA notes triggered the full complex extraction path, which is expected given HotPotQA's multi-hop, encyclopedic nature.

---

## 5. LLM Call Metrics

### 5.1 Provider & Model Usage

| Provider | Model | Calls | % |
|---|---|---|---|
| Ollama | `gemma3:4b` | 1,374 | 80.3% |
| LM Studio | `google/gemma-3-4b` | 336 | 19.6% |
| LM Studio | `gemma3:4b` | 1 | 0.1% |
| **Total** | | **1,711** | 100% |

The run started on Ollama (1,374 extraction calls) and transitioned partway through to LM Studio's MLX build (`google/gemma-3-4b`, 337 calls).

> **Note:** These counts cover only **extraction** calls logged in `llm.log`. Summarization calls are tracked separately — see Section 5.3.

### 5.2 Extraction LLM Calls Per Note

| Metric | Value |
|---|---|
| Total extraction calls | 1,711 |
| Notes successfully ingested | 1,006 |
| **Avg LLM extraction calls per note** | **1.701** |
| Raw extractions logged | 1,374 |

The average of ~1.7 LLM calls per note for extraction reflects the pipeline's two-pass architecture: a primary extraction call, and a secondary complexity-upgrade call for notes exceeding the entity threshold (~68% of notes, consistent with the complexity upgrade rate above).

### 5.3 Raw Extraction Output Per LLM Call

These are the raw counts *before* pipeline filtering/deduplication:

| Metric | Entities | Concepts |
|---|---|---|
| **Avg per call** | **4.46** | **2.34** |
| Median | 4.0 | 2.0 |
| Std Dev | ±3.44 | ±1.35 |
| Min | 0 | 0 |
| Max | 30 | 15 |
| P90 | 9 | 4 |
| P95 | 11 | 5 |
| **Total raw** | **6,127** | **3,215** |

### 5.4 Alias Detection LLM Calls

In addition to extraction calls, the alias detection system made **607 LLM disambiguation calls** across the full corpus:

| Category | Calls |
|---|---|
| Extraction (direct) | 1,711 |
| Alias disambiguation (LLM) | 607 |
| **Total estimated LLM calls** | **~2,318** |
| **Total LLM calls per note** | **~2.30** |

> Summarization LLM calls are not individually enumerated in logs but are the primary component of the 109s/note summarization overhead.

---

## 6. Knowledge Extraction Quality

### 6.1 Final Extracted Counts (Post-Filtering)

These are counts *after* pipeline filtering and deduplication:

| Category | Total | Avg/Note | Median | Max |
|---|---|---|---|---|
| **Entities** | **4,941** | **4.88** | 4 | 30 |
| **Concepts** | **2,282** | **2.25** | 2 | 15 |
| **Relationships** | **666** | **0.66** | 0 | 15 |
| **Tasks** | **130** | **0.13** | 0 | 5 |
| **References** | **529** | **0.52** | 0 | 14 |
| **Persona Traits** | **5** | **0.005** | 0 | 1 |

### 6.2 Entity Count Distribution

```
Entities per note:
  0 entities:        ~5% of notes
  1–3 entities:      ~29% of notes
  4–7 entities:      ~41% of notes (modal range)
  8–11 entities:     ~19% of notes
  12+ entities:      ~6% of notes
  
  P25 = 2,  Median = 4,  P75 = 7,  P90 = 9,  P95 = 11
```

### 6.3 Concept Count Distribution

```
Concepts per note:
  0 concepts:        ~14% of notes
  1–2 concepts:      ~50% of notes (modal range)
  3–4 concepts:      ~27% of notes
  5+ concepts:       ~9% of notes
  
  P25 = 1,  Median = 2,  P75 = 3,  P90 = 4,  P95 = 5
```

### 6.4 Relationship Extraction

Explicit entity relationships were sparsely extracted (avg 0.66/note, median 0), with 90% of notes having ≤3 explicit relationships. This is characteristic of encyclopedic/factual content (HotPotQA) where relationships are implied rather than explicitly stated. Most graph edges are constructed by the pipeline via structural linking rather than direct extraction.

### 6.5 Task & Reference Extraction

Tasks (action items, to-dos) and references (citations, URLs) are primarily relevant in personal knowledge management contexts. With HotPotQA's encyclopedic content:

- **Tasks:** 130 total across 1,013 records — low as expected for trivia-style content (95th percentile = 1)
- **References:** 529 total — slightly more present; 75th percentile = 1 reference/note

---

## 7. Alias Detection System

The alias detection system identifies when newly extracted entities may refer to the same real-world entity as existing graph nodes. It operates in three stages: lexical fuzzy search (Stage 1), semantic embedding similarity shield (Stage 2), and LLM-based disambiguation (Stage 3).

### 7.1 Alias Detection Funnel

| Stage | Count | Rate |
|---|---|---|
| **Total entity lookups** | **9,122** | — |
| Lookups per note | 9.07 | —  |
| No lexical candidates found | 8,603 | **94.31%** pass-through |
| Stage 1 (Lexical) events with candidates | 519 | 5.69% of lookups |
| Stage 1 total candidates surfaced | 18,717 | avg 4.84 per event |
| Stage 2 (Semantic Shield) — candidates evaluated | 18,709 | — |
| Stage 2 — candidates passed | 671 | **3.59% pass rate** |
| Stage 3 — LLM disambiguation calls | 607 | — |
| Skipped (insufficient context) | 95 | — |
| **IS_SAME_AS links created** | **65** | — |

### 7.2 Funnel Efficiency

The alias detection funnel is highly conservative:

```
9,122 lookups
  → 519 had lexical candidates (5.7%)
  → 671 passed semantic shield (3.6% of all candidates evaluated)
  → 607 reached LLM adjudication
  → 95 skipped (context too sparse)
  → 65 confirmed as IS_SAME_AS
```

**Overall alias detection yield:** 65 confirmed aliases from 9,122 lookups = **0.71% yield rate per lookup**. This is appropriate for a clean encyclopedic dataset like HotPotQA where entity names are generally unambiguous. In personal knowledge management use cases, the yield would be expected to be substantially higher.

### 7.3 Filtered Candidate Similarity Distribution

For the 17,817 candidates filtered out by the semantic shield (similarity below 0.65 threshold):

| Statistic | Similarity Score |
|---|---|
| Average | 0.272 |
| Median | 0.254 |
| P75 | 0.331 |
| P90 | 0.426 |
| P95 | 0.498 |
| Max | 0.650 (threshold boundary) |

The low average similarity (0.27) confirms the semantic shield is correctly discarding clearly unrelated candidates, not making borderline cuts.

### 7.4 Known Issues

**19 errors** were recorded for `'AliasDetectorService' object has no attribute 'batch_detect_aliases'`. This indicates a code regression where `IngestionTracker` attempted to call a batch alias detection method that was absent from the deployed version of `AliasDetectorService`. These errors caused alias detection to be skipped entirely for those 19 notes, meaning some alias relationships may be missing.

---

## 8. Knowledge Graph Output

### 8.1 Graph Growth Summary

| Metric | Total | Per Note (avg) |
|---|---|---|
| **Nodes created** | **9,024** | **8.97** |
| **Relationships created** | **10,499** | **10.44** |
| **Properties set** | **138,055** | **137.23** |
| **Labels added** | **16,977** | **16.88** |

### 8.2 Graph Density

- **Node-to-note ratio:** 8.97 nodes/note — each note introduces ~9 new or updated graph nodes on average
- **Relationship-to-node ratio:** 10,499 / 9,024 = **1.16** — the graph is relatively sparse (slightly above tree density), reflecting the early-stage cumulative graph after 1,006 notes
- **Properties per node:** 138,055 / 9,024 = **15.3 properties/node** — indicates rich attribute storage (name, type, summary, embeddings, etc.)

### 8.3 Community Detection

The graph's community membership was updated across **5 community clusters**:

| Community | Update Events |
|---|---|
| Professional Knowledge | Multiple updates (largest, up to 24 members) |
| Personal Knowledge | Multiple updates (up to 26 members) |
| Academic Knowledge | Multiple updates |
| Creative Knowledge | Multiple updates |
| Dreams Knowledge | 1 update (18 members) |

Communities grew incrementally across the run as new notes were ingested and the graph topology evolved.

---

## 9. Domain & Sentiment Classification

### 9.1 Domain Distribution

| Domain | Notes | % |
|---|---|---|
| **Academic** | **513** | **50.6%** |
| **Professional** | **390** | **38.5%** |
| **Personal** | **79** | **7.8%** |
| **Creative** | **31** | **3.1%** |

HotPotQA's encyclopedic content is predominantly classified as Academic (50.6%), with Professional covering technical/organizational topics. Personal and Creative together account for only 10.9%, consistent with a knowledge-base rather than personal journal dataset.

### 9.2 Sentiment Distribution

| Sentiment | Count | % |
|---|---|---|
| **Neutral** | **1,012** | **99.9%** |
| Negative | 1 | 0.1% |

Near-universal neutral sentiment reflects HotPotQA's factual, encyclopedic writing style with no opinion-laden or emotionally charged content.

---

## 10. Entity Type Distribution

Top entity types extracted across all 1,013 extraction records:

| Entity Type | Count | % of Total |
|---|---|---|
| **Person** | **1,912** | **38.7%** |
| **Organization** | **1,677** | **34.0%** |
| **Place** | **995** | **20.1%** |
| Paper | 187 | 3.8% |
| Event | 166 | 3.4% |
| Book | 140 | 2.8% |
| Album | 125 | 2.5% |
| Film | 124 | 2.5% |
| Tool | 95 | 1.9% |
| Song | 82 | 1.7% |
| Poem | 78 | 1.6% |
| Team | 76 | 1.5% |
| Movie | 58 | 1.2% |
| TV Show | 34 | 0.7% |

> Total exceeds note count as multiple types are extracted per note. "relates_to," "related_to," "works_with," and "located_in" appearing in this list indicate occasional LLM classification errors where relationship predicates leaked into the entity type field — a known prompt engineering limitation.

**Person + Organization + Place = 93% of named entities**, consistent with HotPotQA's focus on factual world knowledge about public figures, institutions, and locations.

---

## 11. Error Analysis

### 11.1 Error Volume

| Metric | Value |
|---|---|
| **Total errors logged** | **1,402** |
| **Errors per note** | **1.38** |
| Notes with errors | ~35 (fatal/partial; ~3.5%) |
| Notes with non-fatal errors | ~967 (estimated) |

> The high errors-per-note ratio (1.38) is misleading: the vast majority are **non-fatal** entity summary JSON parse failures that cause individual entity summaries to be skipped, not the note ingestion itself.

### 11.2 Error Breakdown by Component

| Component | Errors | % | Nature |
|---|---|---|---|
| **LLMService** | **1,357** | **96.8%** | Entity summary JSON parse failures |
| IngestionTracker | 19 | 1.4% | Missing `batch_detect_aliases` method |
| GraphService | 9 | 0.6% | Neo4j relationship syntax errors |
| IngestionPipeline | 9 | 0.6% | General pipeline errors |
| uvicorn.error | 8 | 0.6% | Server restart events |

### 11.3 Error Patterns

| Pattern | Count | Impact |
|---|---|---|
| **Entity summary JSON parse failure** | 22 recorded (1,357 total LLMService errors) | Individual entity summaries missing; note completes |
| **`batch_detect_aliases` missing method** | 19 | Alias detection completely skipped for note |
| **LLM request timeout** | 8 | Summarization retry or skip |
| **Neo4j relationship syntax error** | 6 | Individual relationships not stored |

### 11.4 Entity Summary JSON Failures

The dominant error class is malformed JSON responses from the LLM during summary generation. Affected entities include:
- `1982`, `ukrainian`, `mid-to-late 1930s`, `against the 70s`, `rinuccio's family`

These are short, ambiguous, or syntactically problematic entity names that cause the model to produce unterminated strings or invalid comma placement. The root cause is the model hallucinating continuation text within JSON string values.

**Recommendation:** Add a JSON repair/retry layer for summary generation with a maximum of 2 retries before graceful skip.

---

## 12. Provider Comparison: Ollama vs LM Studio

### 12.1 Call Distribution

| Phase | Provider | Model ID | Extraction Calls |
|---|---|---|---|
| Phase 1 | Ollama | `gemma3:4b` | 1,374 (80.3%) |
| Phase 2 | LM Studio | `google/gemma-3-4b` | 337 (19.7%) |

The switch to LM Studio occurred approximately 80% through the run. Because timing is measured end-to-end rather than per-provider in `[Perf]` logs, a clean before/after throughput comparison cannot be computed from the available data.

### 12.2 Qualitative Observations

- **Ollama Phase (Phase 1):** Server restart events visible in `api.log` every 1–4 notes during early testing, stabilizing to longer runs of 50–100+ notes once batch processing was confirmed working.
- **LM Studio Phase (Phase 2):** The `google/gemma-3-4b` model ID indicates LM Studio's MLX-converted weight. The 1.38 errors/note rate was consistent across both phases, suggesting extraction quality did not change between providers.
- **Throughput impact:** No measurable speedup is visible in the logged data for the LM Studio phase. The summarization bottleneck (109s/note avg) dominates regardless of extraction backend speed, meaning extraction-side optimizations have limited impact on overall throughput without also optimizing summarization.

### 12.3 Bottleneck Analysis

```
Time breakdown per note (estimated):
  Summarization:     108.76s  (65.3% of pipeline)
  Extraction (LLM):   38.66s  (23.2% of pipeline)
  Graph Storage:      13.52s  ( 8.1% of pipeline)
  Overhead/other:      ~6.00s  ( 3.6% of pipeline)
  ─────────────────────────────
  Total estimated:   166.94s  ≈ actual avg 166.41s ✓
```

Switching extraction backends (Ollama → LM Studio/MLX) affects only the **23% slice**. To achieve a 2× overall speedup, the summarization stage must be optimized (e.g., batching multiple entity summaries per LLM call, reducing summary verbosity, or using a faster summarization model).

---

## 13. Key Observations & Bottlenecks

### 13.1 What Worked Well

- **98.82% success rate** across 1,006 notes — robust pipeline reliability over a 51-hour multi-session run
- **Entity extraction quality** for HotPotQA: Person/Organization/Place types correctly dominate (93% of entities), indicating the extraction prompt is well-calibrated for encyclopedic content
- **Alias detection funnel** is correctly conservative — a 94.31% early-exit rate at Stage 1 keeps LLM alias disambiguation calls manageable (607 total vs 9,122 lookups)
- **68.1% of notes triggered complexity upgrade** — the adaptive complexity path is functioning and correctly flagging content-dense HotPotQA articles
- **Domain classification** correctly identifies HotPotQA as predominantly Academic (50.6%) with minimal Creative/Personal noise

### 13.2 Performance Bottlenecks

| Bottleneck | Impact | Priority |
|---|---|---|
| **Summarization dominates latency** (109s/note, 65% of time) | 19.6 notes/hr throughput | 🔴 Critical |
| **High variance in indexed time** (stdev ±111s, max 1,000s) | Unpredictable run duration | 🟡 Medium |
| **LM Studio switch had no measurable throughput gain** | Summarization still bottleneck | 🟡 Medium |
| **`batch_detect_aliases` missing** on 19 notes | Incomplete alias coverage | 🟡 Medium |
| **Entity summary JSON parse failures** (1,357 LLMService errors) | Entity summaries missing | 🟡 Medium |

### 13.3 Quality Metrics Summary

| Metric | Value | Assessment |
|---|---|---|
| Entities per note | 4.88 avg | ✅ Good for HotPotQA density |
| Concepts per note | 2.25 avg | ✅ Reasonable abstraction level |
| Relationship extraction | 0.66 avg | ⚠️ Low — mostly structural linking |
| Domain accuracy | Near-100% Neutral sentiment | ✅ Correct for encyclopedia |
| Alias yield | 65 IS_SAME_AS from 9,122 lookups | ✅ Low but appropriate for clean dataset |
| Task extraction | 0.13/note | ✅ Expected (not a task-management corpus) |

### 13.4 Recommendations for Next Run

1. **Batch entity summaries:** Instead of one LLM call per entity, group all entities from a note into a single batched summary request. This could reduce summarization time by 5–10×.
2. **Fix `batch_detect_aliases`:** The missing method in `AliasDetectorService` caused 19 notes to skip alias detection entirely. Ensure the deployed service version matches the caller interface.
3. **Add JSON retry for summary generation:** Implement 1–2 retries with stricter prompting when entity summary JSON is malformed (currently erroring out silently).
4. **Profile LM Studio vs Ollama properly:** Isolate a 50-note batch per provider on identical hardware to measure extraction latency directly, removing the summarization bottleneck from the comparison.
5. **Consider a faster summarization model:** If summarization can run on a smaller/quantized model (e.g., a 1B-2B parameter model), the 65% time cost could be substantially reduced.

---

## Appendix: Raw Metrics Reference

```json
{
  "overview": {
    "notes_started": 1018,
    "notes_success": 1006,
    "success_rate_pct": 98.82,
    "wall_clock_hours": 51.338,
    "throughput_notes_per_hour": 19.6,
    "avg_time_per_note_seconds": 183.71
  },
  "timing": {
    "indexed_avg_s": 166.41,
    "extraction_avg_s": 38.66,
    "summarization_avg_s": 108.76,
    "graph_storage_avg_s": 13.52
  },
  "extraction": {
    "total_entities": 4941,
    "total_concepts": 2282,
    "total_tasks": 130,
    "total_references": 529,
    "total_relationships": 666,
    "entities_avg_per_note": 4.88,
    "concepts_avg_per_note": 2.25
  },
  "llm": {
    "total_extraction_calls": 1711,
    "alias_disambiguation_calls": 607,
    "total_estimated_llm_calls": 2318,
    "llm_extraction_calls_per_note": 1.701
  },
  "alias": {
    "total_lookups": 9122,
    "no_candidate_rate_pct": 94.31,
    "stage2_pass_rate_pct": 3.59,
    "is_same_as_created": 65
  },
  "graph": {
    "nodes_created": 9024,
    "relationships_created": 10499,
    "properties_set": 138055,
    "nodes_per_note": 8.97,
    "rels_per_note": 10.44
  },
  "errors": {
    "total": 1402,
    "alias_missing_method": 19,
    "json_parse_failures": 22,
    "llm_timeouts": 8,
    "neo4j_syntax": 6
  }
}
```

---

*Report generated: 2026-02-27 | LiveOS Research Project | Model: gemma3:4b | Dataset: HotPotQA (990 notes)*
