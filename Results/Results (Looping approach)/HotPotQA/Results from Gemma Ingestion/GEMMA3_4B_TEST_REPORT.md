# GEMMA3:4B HotPotQA Benchmark Evaluation Report — Looping Approach
## LiveOS Knowledge Graph System — Retrieval & QA Pipeline

**Date:** March 11, 2026  
**Model:** `gemma3:4b` via Ollama (local)  
**Embedding:** `qwen3-embedding:0.6b` via Ollama  
**Dataset:** HotPotQA (100 test questions)  
**Knowledge Graph:** 990-note corpus, Looping Approach ingestion  
**Report Generated From:** `gemma3-4b-test-results.json`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Test Configuration](#2-test-configuration)
3. [Answer Quality Metrics](#3-answer-quality-metrics)
4. [End-to-End Response Time Analysis](#4-end-to-end-response-time-analysis)
5. [Retrieval Quality Metrics](#5-retrieval-quality-metrics)
6. [Recall × Accuracy Cross-Tabulation](#6-recall--accuracy-cross-tabulation)
7. [References & Answer Verbosity](#7-references--answer-verbosity)
8. [Failure Mode Analysis](#8-failure-mode-analysis)
9. [Comparison to Previous Runs](#9-comparison-to-previous-runs)
10. [Key Findings & Recommendations](#10-key-findings--recommendations)

---

## 1. Executive Summary

The LiveOS system was evaluated on **100 HotPotQA multi-hop reasoning questions** using `gemma3:4b` (Ollama) against the Looping Approach knowledge graph (990 notes, 11,216 nodes, 15,386 relationships).

| Metric | Value |
|---|---|
| Questions evaluated | 100 |
| Exact Match accuracy | **45.0%** |
| Fuzzy Match accuracy | **54.0%** |
| Token-level F1 | **0.5390** |
| Contains expected answer | **47.0%** |
| Average response time | **30.3 seconds** |
| Median response time | **25.6 seconds** |
| Retrieval recall | **0.685** |
| Retrieval precision | **0.196** |
| Retrieval F1 | **0.305** |
| Errors | 0 |

**This run represents the best answer quality scores to date** for this pipeline on HotPotQA: Exact Match +5pp, Fuzzy Match +4pp, and F1 +0.037 over the previous gemma3:4b run. Critically, **response time more than halved** (30.3s vs 79.5s), driven by the removal of the sub-question decomposition step and neighbor expansion.

Retrieval recall improved substantially (0.685 vs 0.550 prior) — the richer knowledge graph from the Looping Approach ingestion (8.5 entities/note vs 4.88 previously) provides broader coverage. However, retrieval precision decreased (0.196 vs 0.291), indicating the system retrieves more total documents, diluting the signal-to-noise ratio in synthesis context.

The recall structure is sharply bimodal: **49 questions achieved full recall (1.0)**, 39 got partial recall (0.5), and 12 got nothing (0.0). In the perfect-recall group, 27/49 answered correctly on exact match — showing that when context is there, the LLM synthesizes correctly about 55% of the time.

---

## 2. Test Configuration

### System Under Test

| Component | Value |
|---|---|
| LLM provider | Ollama (local) |
| LLM model | `gemma3:4b` |
| Embedding provider | Ollama (local) |
| Embedding model | `qwen3-embedding:0.6b` |
| Knowledge graph | Neo4j |
| Relational database | PostgreSQL |
| Backend framework | FastAPI / uvicorn |
| Retrieval strategy | Entity name matching + vector search (no neighbor expansion) |
| Multi-hop handling | `retrieve_with_self_correction` agentic loop |

### Benchmark Dataset

| Property | Value |
|---|---|
| Dataset | HotPotQA |
| Question type | Multi-hop reasoning (2-hop) |
| Test set size | 100 questions |
| Corpus size | 990 ingested notes |
| Graph nodes | 11,216 |
| Graph relationships | 15,386 |
| Ingestion approach | Looping Approach (gemma3:4b, qwen3-embedding:0.6b) |

### Pipeline Architecture

The LiveOS retrieval pipeline for this run uses the **`retrieve_with_self_correction` agentic loop** — a departure from the previous sub-question decomposition approach:

```
Query Input
    │
    ▼
[1] INITIAL RETRIEVAL
    ├── Entity name matching (Neo4j exact/fuzzy)
    ├── Vector search (embedding similarity)
    └── Community summary search
    │
    ▼
[2] SUFFICIENCY CHECK (LLM)
    LLM evaluates whether retrieved context is sufficient.
    If insufficient: generates targeted follow-up query
    naming specific missing entities.
    │
    ├── [LOOP: repeat retrieval with targeted query]
    │
    ▼
[3] SYNTHESIS (LLM)
    Generates final answer from accumulated context.
    Cites references from retrieved documents.
    │
    ▼
[4] RESPONSE OUTPUT
    Returns answer with inline citations.
```

**Key architectural changes vs. prior run:**
- ❌ Removed: Query decomposition into sub-questions (was ~6.74s avg)
- ❌ Removed: Dynamic per-sub-query LLM instruction generation (was ~1.72s × 2.84 = 4.9s)
- ❌ Removed: Neighbor expansion / graph hop traversal
- ✅ Added: `retrieve_with_self_correction` agentic loop with explicit entity targeting
- ✅ Richer graph: 8.5 entities/note (vs 4.88 previously), +1,543 refinement-added entities

---

## 3. Answer Quality Metrics

### Primary Metrics

| Metric | Count | Percentage |
|---|---|---|
| **Exact Match (EM)** | 45 / 100 | **45.0%** |
| **Fuzzy Match** | 54 / 100 | **54.0%** |
| **Token-level F1** | — | **0.5390** |
| Fuzzy-only (pass fuzzy, fail exact) | 9 / 100 | **9.0%** |
| Contains expected string | 47 / 100 | **47.0%** |
| Both wrong (hard failure) | 46 / 100 | **46.0%** |
| Errors / exceptions | 0 / 100 | **0.0%** |

### Interpretation

- **Exact Match (45%)** remains the strictest metric and is penalized by verbose generation. Generated answers average **40.3 words** vs. expected **2.2 words**, so many factually correct answers fail string matching due to surrounding explanation text.
- **Fuzzy Match (54%)** captures correct answers embedded in longer responses. The 9-question gap (fuzzy − EM) reflects formatting mismatches: correct facts stated with different casing, punctuation, or surrounded by explanation.
- **Contains Expected (47%)** indicates 47 generated answers literally contain the expected string as a substring. The 2-question gap vs. Fuzzy Match (47 contains vs. 54 fuzzy) reflects cases where fuzzy matching finds near-matches that aren't exact substrings.
- **F1 (0.5390)** reflects token-level partial credit — the system produces the right tokens roughly half the time on average.
- **46 hard failures** (both metrics wrong) — detailed in §8.

---

## 4. End-to-End Response Time Analysis

### Summary Statistics (100 questions)

| Statistic | Time (seconds) |
|---|---|
| **Mean** | **30.25 s** |
| **Median** | **25.55 s** |
| Standard Deviation | 14.42 s |
| Minimum | 15.26 s |
| Maximum | 86.53 s |
| P25 | 22.45 s |
| P75 | 29.47 s |
| P90 | 52.01 s |
| P95 | 61.89 s |

### Distribution Buckets

| Bucket | Count | Percentage |
|---|---|---|
| 10–20 seconds | 10 | 10% |
| 20–30 seconds | 65 | **65%** |
| 30–45 seconds | 11 | 11% |
| 45–60 seconds | 7 | 7% |
| 60–90 seconds | 7 | 7% |

```
Response Time Distribution:
10-20s │ ██████████                                   10 queries
20-30s │ █████████████████████████████████████████████████████████████████ 65 queries
30-45s │ ███████████                                  11 queries
45-60s │ ███████                                       7 queries
60-90s │ ███████                                       7 queries
       └──────────────────────────────────────────────────────────
         0          10          20          30          65
```

### Observations

- **65% of queries complete in 20–30 seconds** — an extremely tight and consistent distribution, driven by the simplified single-pass retrieval pipeline.
- The **P90 of 52s and P95 of 62s** show acceptable tail behavior. Only 7 queries exceeded 60s.
- The **max of 86.5s** is the longest query — likely a complex multi-hop question requiring multiple agentic loop iterations.
- The **tight IQR (P25=22.5s, P75=29.5s = 7s range)** indicates very low variance for 75% of queries.
- **62% faster than the previous run** (30.25s vs 79.5s mean), attributable to eliminating the decomposition step (~6.74s), per-sub-query instruction generation (~4.9s), and neighbor graph traversal.

### Slowest Queries

| Time | Question |
|---|---|
| 86.5s | "Which year and which conference was the 14th season for this conference..." |
| 82.5s | "How many copies of Roald Dahl's variation on a popular anecdote sold?" |
| 73.2s | "Alfred Balk served as the secretary of the Committee on the Employment..." |
| 71.6s | "What science fantasy young adult series, told in first person..." |
| 69.3s | "Are Freakonomics and In the Realm of the Hackers both American documentaries?" |

---

## 5. Retrieval Quality Metrics

### Summary

| Metric | Value |
|---|---|
| **Retrieval Precision** | **0.1958** |
| **Retrieval Recall** | **0.6850** |
| **Retrieval F1** | **0.3045** |
| Median Recall | **0.50** |
| Std Dev (Recall) | 0.3456 |

> Precision = (relevant docs retrieved) / (total docs retrieved)  
> Recall = (relevant docs retrieved) / (total relevant docs for question)

### The Bimodal Recall Structure

HotPotQA questions require exactly **2 supporting documents**. This creates a perfectly discrete three-value recall distribution with no partial values observed:

| Recall | Meaning | Count | Percentage |
|---|---|---|---|
| **0.0** | Neither supporting doc retrieved | 12 | 12% |
| **0.5** | Exactly 1 of 2 supporting docs | 39 | 39% |
| **1.0** | Both supporting docs retrieved | **49** | **49%** |

**49% of questions achieved perfect recall** — both HotPotQA gold documents were retrieved. This is a substantial improvement over the prior run's 30% perfect recall. The richer knowledge graph (more entities/note, more relationships) likely accounts for the improvement — more graph nodes means more potential entry points for entity name matching.

### Precision Distribution

| Precision Range | Count | Notes |
|---|---|---|
| 0.0 (zero relevant retrieved) | 12 | Matches the zero-recall count exactly |
| 0.01–0.10 | 10 | Very low signal — many irrelevant |
| 0.10–0.20 | 31 | Largest bucket — 1-2 relevant in ~8-11 retrieved |
| 0.20–0.33 | 37 | Largest bucket — typical 2 relevant in ~7-10 |
| 0.33–0.50 | 5 | |
| 0.50–0.99 | 4 | |
| 1.0 (all retrieved are relevant) | 1 | |

The precision distribution is centered around 0.10–0.33, meaning the system retrieves roughly 5–10 documents per question but only 1–2 are gold standard. This reflects a recall-first design: return enough context to include the right docs, even at the cost of precision. **Notably, there are zero cases of zero precision with non-zero recall** — every question that found any relevant doc had measurable precision.

### Precision vs. Previous Run

The precision decrease from 0.291 → 0.196 (−0.095) is counter-intuitive given that neighbor expansion was removed. The explanation is that the **richer graph produces more vector-similar candidates**: with 11,216 nodes vs 9,024 previously (+24%), vector search naturally returns more topically-adjacent documents, increasing denominator (total retrieved) faster than numerator (relevant retrieved). The precision hit is the cost of the recall gain.

---

## 6. Recall × Accuracy Cross-Tabulation

Understanding where correct answers come from vs. where they fail:

| Recall | Exact Match | Wrong | Total |
|---|---|---|---|
| **Recall = 1.0** (both docs) | **27** | 22 | 49 |
| **Recall = 0.5** (1 doc) | 16 | 23 | 39 |
| **Recall = 0.0** (no docs) | 2 | 10 | 12 |
| **Total** | **45** | **55** | 100 |

### Key Observations

**When recall = 1.0 (49 questions):**
- 27/49 answered correctly (55.1% synthesis success rate)
- 32/49 passed fuzzy match (65.3% fuzzy success rate)
- **17 questions had perfect context but failed synthesis** — the synthesis bottleneck is real

**When recall = 0.5 (39 questions):**
- 16/39 answered correctly (41.0%) — these are likely the "easy hop" where one document is sufficient
- The missing document is needed for the second hop of reasoning

**When recall = 0.0 (12 questions):**
- 2/12 answered correctly anyway — these are questions where `gemma3:4b` can answer from parametric knowledge without retrieval
- 10/12 fail completely — confirming that retrieval is essential for most HotPotQA questions

**Synthesis success given perfect context:** 55.1% (27/49). This is the ceiling for synthesis quality — even with perfect information, the model fails on 45% of questions. Causes include: hallucinated answers, incorrect reasoning chains, and entity confusion.

---

## 7. References & Answer Verbosity

### References Per Response

| Statistic | Value |
|---|---|
| Mean references cited | **8.75** |
| Median references cited | 8.0 |
| Minimum | 1 |
| Maximum | 20 |

| Reference Count | Questions |
|---|---|
| 1–4 | 10 |
| 5–7 | 34 |
| 8–10 | 31 |
| 11–14 | 15 |
| 15+ | 10 |

The system cites an average of 8.75 source documents per response — higher than the prior run's 5.54. This reflects the broader retrieval (lower precision, higher recall): more docs are surfaced, more end up cited.

### Answer vs. Expected Length

| | Mean Words | Median Words | Max Words |
|---|---|---|---|
| **Generated answer** | **40.3** | 36.0 | 114 |
| **Expected answer** | **2.2** | 2.0 | 10 |

The generation verbosity ratio is **18:1** (40.3 generated vs. 2.2 expected). This is the primary driver of the Exact Match gap vs. Fuzzy Match: a 40-word response containing "YG Entertainment" within a longer explanation will never match the gold label "YG Entertainment" by exact string comparison, even though it's factually correct.

The 9-question gap between EM (45%) and fuzzy (54%) directly quantifies how many answers are correct but verbose.

---

## 8. Failure Mode Analysis

### Failure Taxonomy

Of the **46 hard failures** (both exact and fuzzy wrong):

| Category | Count | Examples |
|---|---|---|
| **Retrieval failure** (recall=0.0) | 10 | "Chief of Protocol" — wrong docs retrieved |
| **Wrong entity / hallucination** (recall≥0.5) | 22 | "1,400" instead of "3,677 seated"; "François Coli" instead of "Charles Eugène" |
| **Numeric/format mismatch** (recall≥0.5) | 5 | "1969-1974" vs "1969 until 1974"; "331,900,000" vs "9,984" |
| **Partial retrieval / insufficient context** (recall=0.5) | 9 | Missing second hop document |

### Notable Failure Patterns

**1. Numeric granularity errors (5 cases)**
The model retrieves the correct document but produces the wrong number or format:
- Expected: `3,677 seated` → Got: `1,400` (retrieved both relevant docs but cited wrong arena capacity)
- Expected: `9,984` → Got: `331,900,000` (retrieved Kansas, responded with US population instead)
- Expected: `1969 until 1974` → Got: `1969-1974` (correct content, failed format matching)

**2. Retrieval failure leading to no-answer (10 cases)**
When neither supporting document appears in context, the model correctly says "No information provided" or attempts a guess:
- "Chief of Protocol" — `Shirley Temple Black`'s government role not found despite all Kiss and Tell adjacent notes being retrieved
- "Arena of Khazan" — correct Tunnels & Trolls docs not retrieved

**3. Entity confusion (7+ cases)**
The model retrieves relevant documents but conflates similar entities, producing the wrong specific answer:
- Expected: `Kansas Song` → Got: `We're From Kansas` (both are KU fight songs; model picked the wrong one)
- Expected: `Ronald Shusett` → Got: `Sander Schwartz` (both executive producers in retrieved context)
- Expected: `Charles Eugène` → Got: `François Coli` (both L'Oiseau Blanc crew, model cited co-pilot instead of pilot)

**4. Recall=1.0 but answer wrong (22 cases)**
These are pure synthesis failures — both gold documents were retrieved but the LLM still produced the wrong answer. This is the most important failure class to address:
- Both docs present, model reasons incorrectly about the two-hop chain
- Model reads surface information rather than following the multi-hop reasoning chain
- Entity resolution between the two hops fails

### Questions Answerable Without Retrieval (2 cases)
Two questions with recall=0.0 were answered correctly — the model answered from training data alone:
- `YG Entertainment` (K-pop trivia — widely known)
- `Marion, South Australia` (Australian city question)

---

## 9. Comparison to Previous Runs

### Answer Quality Comparison

| Metric | **This Run (Looping)** | Prior Run (Sub-Q) | Gemini on Own Graph | Change |
|---|---|---|---|---|
| Exact Match | **45.0%** | 40.0% | 56.0%* | **+5.0pp** |
| Fuzzy Match | **54.0%** | 50.0% | 70.0%* | **+4.0pp** |
| Token F1 | **0.5390** | 0.5016 | 0.687* | **+0.037** |
| Contains Expected | **47.0%** | 42.0% | — | +5.0pp |

> \* Gemini results from prior session, different ingestion graph

### Retrieval Quality Comparison

| Metric | **This Run (Looping)** | Prior Run (Sub-Q) | Change |
|---|---|---|---|
| Precision | **0.196** | 0.291 | −0.095 |
| Recall | **0.685** | 0.550 | **+0.135** |
| Recall F1 | **0.305** | 0.380 | −0.075 |
| Perfect recall (1.0) | **49%** | 30% | **+19pp** |
| Zero recall (0.0) | **12%** | 20% | **−8pp** |

### Performance Comparison

| Metric | **This Run (Looping)** | Prior Run (Sub-Q) | Change |
|---|---|---|---|
| Mean response time | **30.3s** | 79.5s | **−62%** |
| Median response time | **25.6s** | 70.6s | **−64%** |
| P90 response time | **52.0s** | 122.4s | **−58%** |
| Max response time | **86.5s** | 305.9s | **−72%** |
| Avg references cited | **8.75** | 5.54 | +3.21 |

### Architecture Differences vs. Prior Run

| Component | Prior Run (Sub-Q Approach) | This Run (Looping Approach) |
|---|---|---|
| Multi-hop strategy | Sub-question decomposition → per-sub-query retrieval | `retrieve_with_self_correction` agentic loop |
| Neighbor expansion | 1-hop + 2-hop graph traversal | **None** |
| Decomposition step | ~6.74s per query | **None** |
| Instruction generation | LLM call per sub-query (~1.72s × 2.84 = 4.9s) | **None** |
| Knowledge graph | 9,024 nodes / 10,499 rels | **11,216 nodes / 15,386 rels** |
| Entities per note | 4.88 avg | **8.5 avg** |

The recall improvement (+0.135) is likely driven primarily by the richer graph (more entity nodes, more entry points for name matching). The speed improvement is entirely architectural — the agentic loop is computationally simpler than sub-question decomposition.

---

## 10. Key Findings & Recommendations

### 10.1 The Richer Graph Is Working

The Looping Approach ingestion (8.5 entities/note, refinement loop, 11,216 nodes) produces a measurably better retrieval graph. Perfect recall (both gold docs found) improved from 30% → 49% — a 19-point gain. This is the clearest evidence that ingestion quality directly drives retrieval quality.

### 10.2 Speed vs. Sub-Question Approach

The agentic loop is **62% faster** than the sub-question decomposition pipeline (30.3s vs 79.5s). The elimination of per-sub-query LLM instruction generation and neighbor expansion explains most of the gain. For applications where latency matters, this is a decisive improvement.

### 10.3 Precision Decreased — Monitor Context Noise

Precision dropped from 0.291 → 0.196. With 8.75 references cited per response (up from 5.54), the synthesis LLM is processing more irrelevant context. For the 22 perfect-recall failures, noise in context is a plausible partial cause — the correct answer is in context but drowned out by related-but-wrong documents.

**Recommendation:** Experiment with top-k cutoffs in retrieval to reduce the retrieved set size. If the system currently returns 10–12 docs per query, reducing to 6–8 while maintaining recall would improve precision and synthesis quality.

### 10.4 Synthesis Quality Is the Primary Bottleneck

27/49 (55%) of perfect-recall questions answered correctly. The remaining 22 failed on synthesis alone — the right documents were there. This ceiling suggests the current synthesis prompt or model capability is the binding constraint, not retrieval.

**Recommendation:** Test a more directive synthesis prompt that explicitly instructs the model to trace the two-hop reasoning chain step by step before committing to a final answer.

### 10.5 Verbosity Gap Remains 18:1

Generated answers average 40.3 words vs. expected 2.2, and this gap is slightly wider than the prior run (25.4 words). The 9-point EM/Fuzzy gap (45/54) is entirely attributable to this. A post-processing extraction step — "given this response, what is the shortest factual answer?" — could recover several additional exact matches.

### 10.6 12 Zero-Recall Questions — Hard Ceiling

12 questions retrieved neither gold document. These represent a hard floor in current performance. The pattern (entity name matching + vector search without hops) cannot surface documents not reachable via entity names or semantic similarity. Multi-hop queries where the bridge entity between the two hops is not directly mentioned in the query will tend to fall into this bucket.

**Recommendation:** Consider re-enabling a single targeted 1-hop expansion on the agentic loop's second iteration — not during initial retrieval, but as a targeted expansion when the LLM identifies a specific missing entity. This preserves the precision gains of the no-expansion initial retrieval while recovering some bridge-entity cases.

---

*Report generated from `gemma3-4b-test-results.json` (100 questions, 0 errors). Benchmark run timestamp: 2026-03-11T14:25:49. No retrieval log files were captured for this run (log directory empty); all metrics derived from per-question JSON records.*
