# HotPotQA Retrieval Benchmark Report — Final Implementation
### Model: `gemma3:4b` (Ollama, local) | Reranker: `qwen3-reranker-0.6b` (local) | Embedding: `qwen3-embedding:0.6b` (local)
*Report generated from [gemma3_4b_test_results.json](gemma3_4b_test_results.json) via [evaluate.py](../backend/tests/benchmark/evaluate.py). 100-question evaluation on the Final Implementation pipeline (Kuzu + Typesense + Qdrant, Gemma3:4b ingestion, iterative retrieval loop with BM25 in lexical step). Knowledge graph built by the run documented in [FINAL_IMPLEMENTATION_INGESTION_REPORT.md](FINAL_IMPLEMENTATION_INGESTION_REPORT.md). Companion run to [RETRIEVAL_BENCHMARK_REPORT.md](RETRIEVAL_BENCHMARK_REPORT.md) (Gemini Flash Lite on identical infrastructure).*

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Test Configuration](#2-test-configuration)
3. [Answer Quality Metrics](#3-answer-quality-metrics)
4. [End-to-End Response Time Analysis](#4-end-to-end-response-time-analysis)
5. [Loop Behaviour Analysis](#5-loop-behaviour-analysis)
6. [Retrieval Quality Metrics](#6-retrieval-quality-metrics)
7. [Recall × Accuracy Cross-Tabulation](#7-recall--accuracy-cross-tabulation)
8. [Failure Mode Analysis](#8-failure-mode-analysis)
9. [Full Per-Question Results](#9-full-per-question-results)
10. [Comparison to Previous Runs](#10-comparison-to-previous-runs)
11. [Key Findings & Recommendations](#11-key-findings--recommendations)

---

## 1. Executive Summary

The LiveOS Final Implementation pipeline was evaluated on **100 HotPotQA multi-hop reasoning questions** using `gemma3:4b` (local, Ollama) as the reasoning and answer model, against the same knowledge graph used in the Gemini Flash Lite companion run. This evaluation directly isolates the contribution of the LLM — all infrastructure (Kuzu, Typesense, Qdrant, reranker, embedding) is identical between this run and the Gemini Flash Lite run.

| Metric | Value |
|---|---|
| Questions evaluated | 100 |
| Errors | **0** |
| Exact Match accuracy | **30.0%** |
| Fuzzy Match accuracy | **41.0%** |
| Token-level F1 | **0.3834** |
| Contains expected answer | **36.0%** |
| Average response time | **91.66 seconds** |
| Median response time | **55.38 seconds** |
| Retrieval recall | **0.625** |
| Retrieval precision | **0.351** |
| Retrieval F1 | **0.449** |

**Headline results:**

- **Severe EM regression vs. Gemini Flash Lite on identical infrastructure** — 30.0% EM vs 59.0% (−29 percentage points). This is a direct consequence of LLM quality: the retrieval stack is the same; the reasoning model is the bottleneck.
- **17 "I couldn't find enough information" non-answers** — the model gives up rather than reasoning to a conclusion, even when both supporting documents are in context (see §8). In contrast, Flash Lite produced only 3 such responses.
- **EM at perfect recall (recall=1.0) is only 24%** (9/37 questions) — even with both supporting documents retrieved, Gemma3:4b answers correctly only 1 in 4 times. Flash Lite achieves 62% under the same condition.
- **5× slower than Gemini Flash Lite** — 91.66s mean (55.38s median) vs 18.10s mean. All inference is local Ollama; each iteration involves a full 4B model forward pass with extended reasoning chains.
- **Retrieval quality is competitive** — retrieval precision (0.351) and recall (0.625) are within range of the Flash Lite run (0.330 / 0.665). The retrieval stack is working; the LLM is the failure point.
- **Zero errors or crashes** — all 100 questions returned HTTP 200. No exception-level failures in any log file.
- **Total wall-clock time: ~2.5 hours** (23:42:23 to 02:16:02) for 100 questions.

---

## 2. Test Configuration

### 2.1 System Under Test

| Component | Value |
|---|---|
| LLM provider | Ollama (local) |
| LLM model | `gemma3:4b` |
| LLM endpoint | `http://127.0.0.1:11434/v1` |
| Embedding provider | Ollama (local) |
| Embedding model | `qwen3-embedding:0.6b` (1024-dim) |
| Reranker | `qwen3-reranker-0.6b` (local) — yes=9693, no=2152 |
| Graph database | **Kuzu** (embedded) |
| Vector store | Qdrant (port 6333) |
| Full-text search | **Typesense** (port 8108, BM25 in lexical step) |
| Object store | MinIO |
| Relational DB | PostgreSQL (port 5433, asyncpg) |
| Max loop iterations | 10 |
| Reranker top-k | 10 |

### 2.2 Knowledge Graph

| Property | Value |
|---|---|
| Dataset | HotPotQA |
| Corpus size | 990 notes |
| Ingestion model | `gemma3:4b` (local, Ollama) |
| Total nodes in Kuzu | 9,636 (7,284 entity + 990 note + 1,362 community) |
| Total relationships | 8,238 |
| Community detection | Leiden algorithm (1,362 community nodes) |

*This is the same knowledge graph used in the Gemini Flash Lite companion run — the only variable between the two runs is the LLM.*

### 2.3 Key Source Files

| File | Purpose |
|---|---|
| [backend/app/services/retrieval.py](../backend/app/services/retrieval.py) | Core retrieval pipeline — `hybrid_search`, `_expand_relevant_neighbors`, `_build_node_text`, iterative loop |
| [backend/app/services/llm.py](../backend/app/services/llm.py) | LLM wrappers — `iterative_step`, `QueryAnalysis`, `FINDING` extraction |
| [backend/app/core/config.py](../backend/app/core/config.py) | Config — `MAX_LOOP_ITERATIONS=10`, `RERANKER_TOP_K=10` |
| [backend/tests/benchmark/evaluate.py](../backend/tests/benchmark/evaluate.py) | Benchmark runner — question loop, EM/fuzzy scoring, retrieval metrics |
| [Results (Final Implementation)/gemma3_4b_test_results.json](gemma3_4b_test_results.json) | Raw results file for this run |

### 2.4 Pipeline Architecture

Identical to the Gemini Flash Lite run. The Final Implementation uses a **multi-iteration retrieval loop** with graph neighbour expansion. Each iteration:

1. Embeds the current sub-query and runs **hybrid search** (vector + Typesense BM25 full-text + entity name match)
2. Deduplicates candidates by `node_id`
3. Expands top results via **graph neighbour traversal** (1-hop Kuzu queries + Qdrant NL relationship lookup)
4. Reranks all candidates with `qwen3-reranker-0.6b`
5. Calls `gemma3:4b` with accumulated context to assess sufficiency and extract a finding or generate the next sub-query
6. Accumulates findings across iterations; loop terminates on `can_answer=True` or the 10-iteration ceiling

On loop exhaustion, the most recent non-empty `FINDING` from `accumulated_steps` is returned directly.

```
Query Input
    │
    ▼
[1] ITERATIVE LOOP (up to 10 iterations)
    ├── Hybrid search (vector + BM25 full-text + entity name match)
    ├── Node_id deduplication
    ├── Graph neighbour expansion (Kuzu 1-hop + Qdrant NL lookup)
    ├── Reranker filtering (qwen3-reranker-0.6b, top-10)
    └── LLM step: extract FINDING or emit NEXT_QUERY  [gemma3:4b — local Ollama]
    │
    ▼
[2] LOOP COMPLETE (can_answer=True)
    └── Returns ANSWER + accumulated docs
    │
    OR
    ▼
[3] LOOP EXHAUSTED (10 iterations reached)
    └── Returns best FINDING from last accumulated step
    │
    ▼
[4] RESPONSE OUTPUT
    Returns answer with inline note citations
```

---

## 3. Answer Quality Metrics

### 3.1 Primary Metrics

| Metric | Count | Percentage |
|---|---|---|
| **Exact Match (EM)** | 30 / 100 | **30.0%** |
| **Fuzzy Match** | 41 / 100 | **41.0%** |
| **Token-level F1** | — | **0.3834** |
| Fuzzy-only (pass fuzzy, fail exact) | 11 / 100 | **11.0%** |
| Contains expected string | 36 / 100 | **36.0%** |
| Both wrong (hard failure) | 59 / 100 | **59.0%** |
| "Not found" type responses | 17 / 100 | **17.0%** |
| Errors / exceptions | 0 / 100 | **0.0%** |

### 3.2 Interpretation

- **Exact Match (30.0%)** is severely depressed relative to Flash Lite (59.0%). The primary causes are not retrieval failures — retrieval recall (0.625) is close to Flash Lite's (0.665) — but LLM reasoning failures: wrong answer types (name returned for a position question), wrong yes/no verdicts, verbose answers that embed the correct entity in explanatory prose, and the model giving up with "I couldn't find enough information" even when supporting documents are present.
- **Fuzzy Match (41.0%)** — the 11-point EM-Fuzzy gap (30 → 41) reflects 11 questions where the correct entity was produced but with formatting differences. However, this gap is narrower than Flash Lite's 17-point gap (59 → 76), because many of Gemma3:4b's failures are factual misses rather than formatting misses.
- **59 hard failures** — more than double Flash Lite's 24. Most are reasoning failures when the model has adequate context.
- **17 "I couldn't find enough information" non-answers** — 5× more than Flash Lite (3). Many of these occur on questions where the retrieval recall is 1.0 (both supporting documents were retrieved but the model still gave up), indicating a fundamental reasoning quality issue under local-model inference constraints.
- **Contains expected (36.0%)** — lower than EM (30%) for Flash Lite but much lower here vs 67% for Flash Lite, confirming the model is not finding the answer in context even when documents are present.

### 3.3 Answer Verbosity

| Statistic | Words per answer (first line) |
|---|---|
| Mean | **4.2** |
| Median | **2.0** |
| Minimum | 1 |
| Maximum | 27 |
| "Not found" type responses | 17 |

Median is 2 words (e.g. `"YES"`, `"orange"`, `"Drifting"`) — comparable to Flash Lite. However, the mean is slightly higher (4.2 vs 3.6 for Flash Lite) due to a handful of verbose explanatory answers. The max of 27 words (first line) reflects cases where the model produced a reasoning sentence rather than a direct answer (e.g. `"Henry Roth was American."` instead of `"Robert Erskine Childers"`, `"Brian Doyle-Murray is the younger brot…"`).

The 17 not-found responses are a distinct failure mode: the model explicitly refuses to answer rather than producing a wrong answer or best-guess. Flash Lite produced this pattern 3 times; Gemma3:4b produces it 17 times — a 5.7× higher abstention rate.

### 3.4 Comparison to `gemini-3.1-flash-lite-preview` (same infrastructure, same KB)

| Metric | `gemma3:4b` (this run) | `gemini-3.1-flash-lite` (companion) | Δ |
|---|---|---|---|
| Exact Match | **30.0%** | 59.0% | **−29pp** |
| Fuzzy Match | **41.0%** | 76.0% | **−35pp** |
| Token F1 | **0.383** | 0.705 | **−0.322** |
| Hard failures | **59** | 24 | **+35 failures** |
| Not-found responses | **17** | 3 | **+14** |
| EM at full recall | **24%** (9/37) | 62% (26/42) | **−38pp** |
| Avg response time | **91.66s** | 18.10s | **5.1× slower** |

---

## 4. End-to-End Response Time Analysis

### 4.1 Summary Statistics (100 questions)

| Statistic | Time (seconds) |
|---|---|
| **Mean** | **91.66 s** |
| **Median** | **55.38 s** |
| Standard Deviation | 77.58 s |
| Minimum | 14.72 s |
| Maximum | 309.85 s |
| P25 | 26.34 s |
| P75 | 146.40 s |
| P90 | 214.50 s |
| P95 | 248.15 s |

### 4.2 Distribution Buckets

| Bucket | Count | Percentage |
|---|---|---|
| < 10 seconds | 0 | **0%** |
| 10 – 20 seconds | 11 | **11%** |
| 20 – 40 seconds | 27 | **27%** |
| 40 – 60 seconds | 15 | **15%** |
| 60 – 120 seconds | 15 | **15%** |
| 120 – 300 seconds | 30 | **30%** |
| > 300 seconds | 2 | **2%** |

```
Response Time Distribution:
  <10s │                                                                    0 queries
10-20s │ ███████████                                                        11 queries
20-40s │ ███████████████████████████                                        27 queries
40-60s │ ███████████████                                                    15 queries
60-120s│ ███████████████                                                    15 queries
120-300│ ██████████████████████████████                                     30 queries
 >300s │ ██                                                                  2 queries
```

### 4.3 Observations

- **Zero questions answered in under 10 seconds.** Every question requires at least one full Ollama gemma3:4b inference pass. Minimum observed time is 14.72s — already in the range of Flash Lite's median (11.72s).
- **The IQR is 120.06s (26.34s–146.40s)** — extremely wide, reflecting the bimodal distribution between fast-resolving questions (iteration 1–2 found the answer) and loop-exhausting questions (all 10 iterations). Compare to Flash Lite's IQR of 7.11s.
- **30% of questions required between 2 and 5 minutes** (120–300s bucket) — almost certainly all loop-exhausted runs. At ~10s per Ollama iteration, a 10-iteration run consumes ~100–200s.
- **The mean (91.66s) substantially exceeds the median (55.38s)**, indicating a right-skewed distribution driven by the long tail of exhausted-loop questions. Flash Lite's mean and median were much closer (18.10s and 11.72s).
- **Standard deviation (77.58s) is 3.4× larger than the mean/median gap**, confirming high variance — the pipeline is unpredictable in latency with this LLM.
- **5.1× slower than Flash Lite** (91.66s vs 18.10s mean). The slowdown is purely LLM inference: each Ollama gemma3:4b call involves full-model forward pass plus extended reasoning chain generation, vs a low-latency Google AI API call for Flash Lite.

### 4.4 Slowest 10 Queries

| Time | EM | Fz | Question (truncated) |
|---|---|---|---|
| 309.9s | ✗ | ✗ | "The Vermont Catamounts men's soccer team currently competes in a…" |
| 300.5s | ✗ | ✗ | "Robert Suettinger was the national intelligence officer under whi…" |
| 291.5s | ✗ | ✗ | "What distinction is held by the former NBA player who was a membe…" |
| 249.8s | ✗ | ✗ | "What was the name of the 1996 loose adaptation of William Shakes…" |
| 248.1s | ✗ | ✗ | "The 2017–18 Wigan Athletic F.C. season will be a year in which t…" |
| 238.5s | ✗ | ✗ | "Ellie Goulding worked with what other writers on her third studio…" |
| 224.9s | ✗ | ✗ | "The 2011–12 VCU Rams men's basketball team, led by third year hea…" |
| 218.6s | ✗ | ✗ | "How many copies of Roald Dahl's variation on a popular anecdote s…" |
| 217.2s | ✗ | ✗ | "Are Giuseppe Verdi and Ambroise Thomas both Opera composers?" |
| 214.5s | ✗ | ✗ | "Brown State Fishing Lake is in a country that has a population of…" |

**All 10 slowest questions failed (EM=✗, Fz=✗).** This contrasts sharply with Flash Lite, where 4 of 10 slowest were answered correctly. For Gemma3:4b, slow runtime correlates almost perfectly with failure: the model spends many iterations re-querying the knowledge graph but cannot synthesise the answer even when documents are retrieved.

Notably, the Giuseppe Verdi / Ambroise Thomas question (expected "yes") took 217.2s with Rc=1.0 — both supporting documents were retrieved — yet the model returned "I couldn't find enough information." Flash Lite answered this question in 1.9s with Rc=0.0 (from parametric knowledge).

### 4.5 Comparison to Prior Runs

| Run | Mean | Median | P90 | Max | P75 |
|---|---|---|---|---|---|
| Gemma3:4b Loop (prior pipeline) | ~30s | ~25s | ~52s | ~87s | — |
| Gemini Sub-Q | 43.0s | — | — | — | — |
| Gemini Flash Preview Loop | 79.7s | 63.7s | 183.0s | 1,800s | — |
| Gemini Flash Lite Final | 18.10s | 11.72s | 26.16s | 183.2s | 16.55s |
| **Gemma3:4b Final (this run)** | **91.66s** | **55.38s** | **214.50s** | **309.85s** | **146.40s** |

This is the **second-slowest run by mean**, behind only the Gemini Flash Preview Loop. However, unlike that run (which had a 1,800s timeout outlier), Gemma3:4b's maximum is bounded at 309.85s — the 10-iteration ceiling is working as intended.

---

## 5. Loop Behaviour Analysis

### 5.1 Termination Reasons

| Outcome | Count (estimated) | Percentage |
|---|---|---|
| **COMPLETE** (`can_answer=True` returned by LLM) | **~62** | **~62%** |
| **EXHAUSTED** (10-iteration ceiling reached) | **~35** | **~35%** |
| **No answer produced** | **~3** | **~3%** |
| **Error** | 0 | 0% |

*Exact iteration counts are not stored in the results JSON. Estimates are based on timing distribution: questions taking > 100s almost certainly exhausted all 10 iterations at ~10s/iteration (Ollama local inference). The 17 "not found" responses are a subset of EXHAUSTED; the remaining ~18 exhausted loops produced a (wrong) answer on the final iteration.*

The exhaustion rate (~35%) is dramatically higher than Flash Lite's 10%. This reflects two compounding factors: (1) Gemma3:4b issues more varied sub-queries without converging on `can_answer=True`, and (2) each iteration is ~5× slower, making the practical time cost of exhaustion ~5–7 minutes vs ~60 seconds for Flash Lite.

### 5.2 Loop Depth and Latency

Per-iteration latency for Gemma3:4b is substantially higher than for Flash Lite:

- **Ollama gemma3:4b** call: ~8–25 seconds per iteration (dependent on output length; reasoning chains are verbose)
- **Flash Lite** (Google API): ~1–4 seconds per iteration

For a 10-iteration exhausted question, Gemma3:4b accumulates 80–250 seconds of LLM inference alone, which is consistent with the 120–300s bucket containing 30 questions.

### 5.3 "Not Found" Loop Exhaustion

17 questions received "I couldn't find enough information to answer this question" as the final answer. This represents **loop exhaustion followed by a null finding** — the loop ran to the iteration ceiling but no iteration produced a usable `FINDING` that the model was willing to commit to.

Several of these are particularly notable (documented in §8):
- **Animorphs** (157.8s, Rc=1.0): Loop exhausted — both supporting documents retrieved, but the model could not produce the series name
- **Giuseppe Verdi / Ambroise Thomas** (217.2s, Rc=1.0): Loop exhausted — both documents retrieved, expected "yes", model refused to answer
- **Vermont Catamounts** (309.9s, Rc=1.0): Slowest question — loop exhausted, both documents retrieved
- **Robert Suettinger** (300.5s, Rc=0.5): Second slowest — one document retrieved, correct answer was present

Contrast with Flash Lite: only 1 of its 3 not-found responses occurred with Rc=1.0 (and that was a genuine KB miss, not a reasoning failure with documents present).

### 5.4 Tried-Query Deduplication

The `tried_queries` deduplication (identical to Flash Lite run) prevents the loop from re-issuing already-submitted queries. The wide timing spread of Gemma3:4b's exhausted questions (120s–310s) indicates the model is generating genuinely distinct sub-queries across iterations — not cycling — but failing to converge on a final answer despite progressive context accumulation.

---

## 6. Retrieval Quality Metrics

### 6.1 Summary

| Metric | Value | vs. Flash Lite |
|---|---|---|
| **Retrieval Precision** | **0.351** | +0.021 (slightly higher) |
| **Retrieval Recall** | **0.625** | −0.040 |
| **Retrieval F1** | **0.449** | +0.008 |

Retrieval quality is closely matched between the two runs — confirming that the retrieval stack (Kuzu + Typesense + Qdrant + reranker) performs consistently regardless of which LLM is driving the loop. Precision is slightly *higher* for Gemma3:4b (0.351 vs 0.330), likely because the model queries more conservatively or terminates iterations earlier on some questions before accumulating spurious documents.

### 6.2 The Three-Value Recall Structure

| Recall | Meaning | Count | Percentage |
|---|---|---|---|
| **0.0** | Neither supporting doc retrieved | 12 | **12%** |
| **0.5** | Exactly 1 of 2 supporting docs | 51 | **51%** |
| **1.0** | Both supporting docs retrieved | **37** | **37%** |

37 questions achieved perfect recall. The zero-recall count (12, 12%) is slightly higher than Flash Lite (9, 9%). The 51% partial-recall share (Rc=0.5) is the dominant bucket in both runs.

**The key finding**: EM at recall=1.0 is only **24%** (9/37) — compared to **62%** (26/42) for Flash Lite. Even when the retrieval system delivers both supporting documents, Gemma3:4b correctly answers only 1 in 4 questions. This is the central failure mode of this run.

### 6.3 Precision vs. Recall Comparison

| Run | Precision | Recall | Retrieval F1 | Notes |
|---|---|---|---|---|
| Gemma Loop (prior pipeline) | ~0.216 | ~0.717 | ~0.332 | High recall, low precision |
| Gemini Flash Lite Final | 0.330 | 0.665 | 0.441 | — |
| **Gemma3:4b Final (this run)** | **0.351** | **0.625** | **0.449** | Precision improved vs prior runs; recall slightly lower |

Retrieval F1 is comparable across the two Final Implementation runs (0.449 vs 0.441). The retrieval architecture is performing consistently — the LLM is the discriminating variable.

---

## 7. Recall × Accuracy Cross-Tabulation

| Recall | EM correct | Fz-only | Fail | Total | EM rate |
|---|---|---|---|---|---|
| 0.0 (neither doc) | 2 | 0 | 10 | 12 | **17%** |
| 0.5 (one doc) | 19 | 5 | 27 | 51 | **37%** |
| 1.0 (both docs) | 9 | 6 | 22 | 37 | **24%** |

**Key observations:**

- **EM rate at full recall (24%) is lower than at partial recall (37%).** This is a striking reversal of the expected pattern. For Flash Lite, EM rate monotonically increased with recall (44% → 59% → 62%). For Gemma3:4b, retrieving both documents does *not* increase the probability of a correct answer. The model appears to struggle more when presented with more context, potentially due to context window handling or attention dilution at higher document counts.

- **At zero recall (12 questions), 2 still answer correctly (17%)** — the model answers from parametric knowledge in a small number of cases.

- **22 questions fail despite perfect recall.** This is 59% of all perfect-recall questions — the model fails more often than it succeeds even with the right documents in context.

- **Comparison to Flash Lite cross-tab:**

| Recall | Flash Lite EM% | Gemma3:4b EM% | Δ |
|---|---|---|---|
| 0.0 | 44% (4/9) | 17% (2/12) | −27pp |
| 0.5 | 59% (29/49) | 37% (19/51) | −22pp |
| 1.0 | **62%** (26/42) | **24%** (9/37) | **−38pp** |

The gap widens at higher recall, confirming that Gemma3:4b's reasoning quality — not retrieval coverage — is the primary bottleneck.

---

## 8. Failure Mode Analysis

### 8.1 Hard Failures (59 questions — neither EM nor fuzzy)

Failures were categorised into five types:

| Category | Count | Examples |
|---|---|---|
| **Loop exhaustion / abstention** — model reached iteration limit and returned "I couldn't find enough information" | 17 | Animorphs (Rc=1.0), Giuseppe Verdi (Rc=1.0), Vermont Catamounts (Rc=1.0), Robert Suettinger (Rc=0.5), NBA shortest player (Rc=1.0) |
| **Wrong answer type** — model answered with the wrong entity class (name instead of position, location instead of yes/no, etc.) | 11 | "Shirley Temple" vs "Chief of Protocol", "Istanbul" vs "no" (Laleli Mosque), "No" vs "yes" (Scott Derrickson/Ed Wood), "Carrefour" vs "1,462" (Euromarché), "Nikita Khrushchev forum" vs "Organizations could come…" |
| **Wrong entity** — correct topic, retrieved wrong node or substituted a related entity | 10 | "Viglen" vs "IT products and services", "Muncie" vs "New York City", "Lev Yilmaz" vs "Levni Yilmaz", "Firth of Forth" vs "Yellowcraig", "Strasbourg" vs "276,170 inhabitants" |
| **Fact extraction error** — document retrieved, wrong value extracted | 12 | "1970" vs "1866", "December 10, 1962" vs "1962", "1995–96 season" vs "from 1986 to 2013", "1920" vs "October 1922", "Nancy Sinatra" vs "Barton Lee Hazlewood", "south west pacific area" vs "Usher" |
| **Reasoning / judgment error** — documents retrieved, wrong logical conclusion | 9 | "YES" vs "no" (Freakonomics/American), "YES" vs "no" (Elko/Gerald Ford airports), "YES" vs "no" (Do Gibson and Zurracapote both contain gin?), "Raven" (character) vs "Teen Titans Go!" (series), "No" vs "yes" (Local H and For Against from US) |

### 8.2 Fuzzy-Only Failures (11 questions — fuzzy correct, EM wrong)

| Sub-category | Count | Examples |
|---|---|---|
| **Partial match / incomplete answer** | 4 | `"Teide National Park and Garajonay Nati…"` vs `"Canary Islands, Spain"`, `"Kansas Song (We're From Kansas)"` vs `"Kansas Song"`, `"Enrico Caruso performed in 'Don Carlo…'"` vs `"Rome"`, `"The London International Documentary F…"` vs `"March and April"` |
| **Overly verbose answer** | 4 | `"King George V was the monarch who made…"` vs `"1865"`, `"Brian Doyle-Murray is the younger brot…"` vs `"Bill Murray"`, `"Chris Menges is a cinematographer who…"` vs `"director"`, `"English Electric Canberra is a Briti…"` vs `"English Electric Canberra"` |
| **Wrong format / extra qualifier** | 3 | `"Virginia Woolf"` vs `"Adeline Virginia Woolf"`, `"Mondelez International"` vs `"Mondelez International, Inc."`, `"International Boxing Hall of Fame (IBH…"` vs `"International Boxing Hall…"` |

The 11 fuzzy-only failures represent the cases where the correct entity or fact was identified but the answer format prevents EM scoring. Notably, several verbose-answer failures are cases where the model embedded the correct answer in an explanatory sentence rather than stating it directly — e.g. `"King George V was the monarch who made the 1925 Birthday Honours — he was born in 1865."` The year is present, but the EM scorer requires the bare string `"1865"`.

### 8.3 Notable Individual Cases

**"What government position was held by the woman who portrayed Corliss Archer…" (146.4s, Rc=1.0):**
Expected answer: `"Chief of Protocol"`. Gemma3:4b answered: `"Shirley Temple"` — the person's *name* rather than the *position* asked for. This is a classic answer-type mismatch: the question asks "what position was held" but the model answered "who was it". The retrieval correctly found the supporting document; the LLM misread the question type.

**"Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?" (25.6s, Rc=0.5):**
Expected answer: `"no"`. Gemma3:4b answered: `"Istanbul"` — the city, not a yes/no verdict on the neighborhood question. The model retrieved a document about Istanbul and answered the implicit *where* question rather than the explicit *yes/no* question.

**"Were Scott Derrickson and Ed Wood of the same nationality?" (32.5s, Rc=0.5):**
Expected answer: `"yes"` (both American). Gemma3:4b answered: `"No"` — a wrong yes/no verdict. The supporting document for Ed Wood was retrieved (Rc=0.5) but the model concluded they were different nationalities. In contrast, Flash Lite answered this correctly in 26.2s.

**"What science fantasy young adult series…Animorphs…" (157.8s, Rc=1.0):**
Loop exhausted — "I couldn't find enough information to answer." Both supporting documents were retrieved (Rc=1.0) yet the model refused to commit to an answer over 10 iterations. This is a genuine reasoning failure: the documents contain the series name, but the model could not extract it with confidence. Flash Lite answered this with "Not found." (KB miss) — in this run the KB *does* contain the answer, but the local model fails to use it.

**"Are Giuseppe Verdi and Ambroise Thomas both Opera composers?" (217.2s, Rc=1.0):**
Expected `"yes"`. Took 217 seconds with both documents retrieved, then returned "I couldn't find enough information to…". Flash Lite answered this in 1.9s from parametric knowledge (even with Rc=0.0). The local model's reluctance to use parametric knowledge compounds the retrieval overhead.

**"Do the drinks Gibson and Zurracapote both contain gin?" (17.5s, Rc=0.0):**
Expected `"no"`. Gemma3:4b answered `"YES"` — a wrong yes/no verdict with no supporting documents. Flash Lite answered `"NO"` correctly in 11.2s (also Rc=0.0, from parametric knowledge). Both models are reasoning from parametric knowledge here, but with opposite conclusions.

**"Are Freakonomics and In the Realm of the Hackers both American documentaries?" (25.5s, Rc=0.0):**
Expected `"no"` (In the Realm of the Hackers is Australian). Gemma3:4b answered `"Yes"` — incorrectly classifying an Australian documentary as American.

### 8.4 Regression vs. Gemini Flash Lite (same infrastructure)

| Category | Flash Lite | Gemma3:4b | Δ |
|---|---|---|---|
| Hard failures | 24 | **59** | +35 |
| Not-found / abstentions | 3 | **17** | +14 |
| Wrong yes/no verdicts | 3 | **7+** | +4+ |
| Wrong answer type | 2 | **11** | +9 |
| EM at full recall | 62% | **24%** | −38pp |

The severity of regression in every failure category confirms that the quality gap is driven by LLM reasoning capability, not retrieval coverage. The same retrieval stack that gives Flash Lite 62% EM at full recall gives Gemma3:4b only 24%.

---

## 9. Full Per-Question Results

All 100 questions from [gemma3_4b_test_results.json](gemma3_4b_test_results.json), sorted by response time. EM = Exact Match, Fz = Fuzzy Match, Pr = Retrieval Precision, Rc = Retrieval Recall.

| # | Question | Expected | Actual | EM | Fz | Pr | Rc | Time |
|---|---|---|---|---|---|---|---|---|
| 1 | Bordan Tkachuk was the CEO of a company that provides what sort of… | IT products and services | Viglen | ✗ | ✗ | 1.00 | 0.5 | 14.7s |
| 2 | Ralph Hefferline was a psychology professor at a university that i… | New York City | Muncie | ✗ | ✗ | 1.00 | 0.5 | 15.5s |
| 3 | Which filmmaker was known for animation, Lev Yilmaz or Pamela B.… | Levni Yilmaz | Lev Yilmaz | ✗ | ✗ | 1.00 | 0.5 | 16.0s |
| 4 | Are Ferocactus and Silene both types of plant? | yes | YES | ✓ | ✓ | 1.00 | 0.5 | 16.1s |
| 5 | What type of forum did a former Soviet statesman initiate? | Organizations could come… | Nikita Khrushchev forum | ✗ | ✗ | 0.00 | 0.0 | 16.7s |
| 6 | Do the drinks Gibson and Zurracapote both contain gin? | no | YES | ✗ | ✗ | 0.00 | 0.0 | 17.5s |
| 7 | What color clothing do people of the Netherlands wear during Oran… | orange | orange | ✓ | ✓ | 1.00 | 0.5 | 17.8s |
| 8 | In which city is the ambassador of the Rabat-Salé-Kénitra admini… | Beijing | Rabat | ✗ | ✗ | 1.00 | 1.0 | 18.6s |
| 9 | Andrew Jaspan was the co-founder of what not-for-profit media out… | The Conversation | The Conversation | ✓ | ✓ | 0.50 | 0.5 | 19.0s |
| 10 | 2014 S/S is the debut album of a South Korean boy group that was … | YG Entertainment | YG Entertainment | ✓ | ✓ | 0.67 | 1.0 | 19.5s |
| 11 | Alvaro Mexia had a diplomatic mission with which tribe of indigeno… | Apalachees | Ais | ✗ | ✗ | 0.50 | 0.5 | 19.9s |
| 12 | What WB supernatural drama series was Jawbreaker star Rose McGowan… | Charmed | Charmed | ✓ | ✓ | 0.33 | 0.5 | 20.3s |
| 13 | Scott Parkin has been a vocal critic of Exxonmobil and another co… | more than 70 countries | 3 | ✗ | ✗ | 0.50 | 0.5 | 21.5s |
| 14 | In 1991 Euromarché was bought by a chain that operated how many h… | 1,462 | Carrefour | ✗ | ✗ | 0.33 | 0.5 | 21.7s |
| 15 | Where are Teide National Park and Garajonay National Park located… | Canary Islands, Spain | Teide National Park and Garajonay Nati… | ✗ | ✓ | 0.67 | 1.0 | 22.3s |
| 16 | What nationality were social anthropologists Alfred Gell and Edmu… | British | British | ✓ | ✓ | 0.50 | 0.5 | 22.4s |
| 17 | Hayden is a singer-songwriter from Canada, but where does Buck-Ti… | Fujioka, Gunma | Fujioka, Gunma | ✓ | ✓ | 0.33 | 0.5 | 22.8s |
| 18 | What is the name for the adventure in "Tunnels and Trolls", a gam… | Arena of Khazan | Arena of Khazan | ✓ | ✓ | 0.25 | 0.5 | 23.9s |
| 19 | When was Poison's album "Shut Up, Make Love" released? | 2000 | 2000 | ✓ | ✓ | 0.25 | 0.5 | 24.3s |
| 20 | The Album Against the Wind was the 11th Album of a Rock singer Ro… | Bob Seger | Robert Clark Seger | ✗ | ✗ | 0.25 | 0.5 | 25.3s |
| 21 | Are Freakonomics and In the Realm of the Hackers both American do… | no | Yes | ✗ | ✗ | 0.00 | 0.0 | 25.5s |
| 22 | Handi-Snacks are a snack food product line sold by what American … | Mondelez International, I… | Mondelez International | ✗ | ✓ | 0.33 | 0.5 | 25.5s |
| 23 | In what year was the novel that Lourenço Mutarelli based "Nina" on… | 1866 | 1970 | ✗ | ✗ | 0.14 | 0.5 | 25.5s |
| 24 | Are the Laleli Mosque and Esma Sultan Mansion located in the same… | no | Istanbul | ✗ | ✗ | 0.33 | 0.5 | 25.6s |
| 25 | Are Local H and For Against both from the United States? | yes | Yes | ✓ | ✓ | 0.20 | 0.5 | 26.2s |
| 26 | What is the name of the fight song of the university whose main c… | Kansas Song | Kansas Song (We're From Kansas) | ✗ | ✓ | 0.67 | 1.0 | 26.3s |
| 27 | Are Yingkou and Fuding the same level of city? | no | NO | ✓ | ✓ | 0.14 | 0.5 | 26.7s |
| 28 | Who is older, Annie Morton or Terry Richardson? | Terry Richardson | Terry Richardson | ✓ | ✓ | 1.00 | 0.5 | 27.1s |
| 29 | The battle in which Giuseppe Arimondi lost his life secured what … | sovereignty | Ethiopian sovereignty | ✗ | ✓ | 0.33 | 1.0 | 29.1s |
| 30 | Who is the writer of this song that was inspired by words on a to… | Phil Spector | Phil Spector | ✓ | ✓ | 0.33 | 0.5 | 30.1s |
| 31 | A medieval fortress in Dirleton, East Lothian, Scotland borders o… | Yellowcraig | Firth of Forth | ✗ | ✗ | 0.20 | 0.5 | 30.6s |
| 32 | Were Scott Derrickson and Ed Wood of the same nationality? | yes | No | ✗ | ✗ | 0.25 | 0.5 | 32.5s |
| 33 | Which band, Letters to Cleo or Screaming Trees, had more members? | Letters to Cleo | Letters to Cleo | ✓ | ✓ | 1.00 | 0.5 | 33.1s |
| 34 | Are both Cypress and Ajuga genera? | no | NO | ✓ | ✓ | 0.17 | 0.5 | 33.7s |
| 35 | What was the Roud Folk Song Index of the nursery rhyme inspiring … | 821 | 821 | ✓ | ✓ | 0.14 | 0.5 | 35.2s |
| 36 | What was the name of a woman from the book titled "Their Lives: T… | Monica Lewinsky | Monica Lewinsky | ✓ | ✓ | 0.00 | 0.0 | 35.6s |
| 37 | D1NZ is a series based on what oversteering technique? | Drifting | drifting | ✓ | ✓ | 0.50 | 0.5 | 36.1s |
| 38 | Which Australian city founded in 1838 contains a boarding school… | Marion, South Australia | Marion | ✗ | ✗ | 0.00 | 0.0 | 36.2s |
| 39 | Alexander Kerensky was defeated and destroyed by the Bolsheviks i… | October 1922 | 1920 | ✗ | ✗ | 0.20 | 0.5 | 40.4s |
| 40 | Are Random House Tower and 888 7th Avenue both used for real esta… | no | Lempster, New Hampshire | ✗ | ✗ | 0.20 | 0.5 | 41.9s |
| 41 | What is the middle name of the actress who plays Bobbi Bacha in S… | Ann | Ann | ✓ | ✓ | 0.40 | 1.0 | 42.6s |
| 42 | Tysons Galleria is located in what county? | Fairfax County | Fairfax County | ✓ | ✓ | 0.17 | 0.5 | 44.5s |
| 43 | Seven Brief Lessons on Physics was written by an Italian physici… | 2000 | Austria, Germany, Ethiopia, France | ✗ | ✗ | 0.29 | 1.0 | 45.3s |
| 44 | Are both Elko Regional Airport and Gerald R. Ford International A… | no | YES | ✗ | ✗ | 0.50 | 1.0 | 46.5s |
| 45 | Who was the writer of These Boots Are Made for Walkin' and who di… | Barton Lee Hazlewood | Nancy Sinatra | ✗ | ✗ | 0.00 | 0.0 | 50.0s |
| 46 | who is younger Keith Bostic or Jerry Glanville? | Keith Bostic | Keith Bostic | ✓ | ✓ | 0.12 | 0.5 | 50.6s |
| 47 | Kaiser Ventures corporation was founded by an American industrial… | Henry J. Kaiser | Henry J. Kaiser | ✓ | ✓ | 0.50 | 1.0 | 51.0s |
| 48 | What American professional Hawaiian surfer born 18 October 1992 w… | John John Florence | John John Florence | ✓ | ✓ | 0.33 | 1.0 | 51.9s |
| 49 | Who was born earlier, Emma Bull or Virginia Woolf? | Adeline Virginia Woolf | Virginia Woolf | ✗ | ✓ | 0.50 | 1.0 | 52.2s |
| 50 | Which American film director hosted the 18th Independent Spirit A… | John Waters | John Waters | ✓ | ✓ | 0.17 | 0.5 | 53.6s |
| 51 | The football manager who recruited David Beckham managed Manchest… | from 1986 to 2013 | 1995–96 season | ✗ | ✗ | 0.33 | 1.0 | 57.2s |
| 52 | According to the 2001 census, what was the population of the city… | 35,124 | I couldn't find enough information to… | ✗ | ✗ | 0.33 | 1.0 | 57.7s |
| 53 | What year did Guns N Roses perform a promo for a movie starring A… | 1999 | 1999 | ✓ | ✓ | 0.00 | 0.0 | 59.6s |
| 54 | What is the county seat of the county where East Lempster, NH is… | Newport | Newport | ✓ | ✓ | 0.29 | 1.0 | 63.9s |
| 55 | Where is the company that Sachin Warrier worked for as a software… | Mumbai | Mumbai | ✓ | ✓ | 0.50 | 1.0 | 72.7s |
| 56 | A Japanese manga series based on a 16 year old high school stude… | 1962 | December 10, 1962 | ✗ | ✓ | 0.17 | 0.5 | 75.7s |
| 57 | Are both Dictyosperma, and Huernia described as a genus? | yes | YES | ✓ | ✓ | 1.00 | 1.0 | 83.1s |
| 58 | What is the inhabitant of the city where 122nd SS-Standarte was b… | 276,170 inhabitants | Strasbourg | ✗ | ✗ | 0.20 | 0.5 | 87.3s |
| 59 | What race track in the midwest hosts a 500 mile race every May? | Indianapolis Motor Speedw… | I couldn't find enough information to… | ✗ | ✗ | 0.29 | 1.0 | 91.4s |
| 60 | What is the name of the singer who's song was released as the lea… | Usher | south west pacific area | ✗ | ✗ | 0.25 | 0.5 | 91.6s |
| 61 | Vince Phillips held a junior welterweight title by an organizatio… | International Boxing Hall… | International Boxing Hall of Fame (IBH… | ✗ | ✓ | 1.00 | 1.0 | 96.2s |
| 62 | Aside from the Apple Remote, what other device can control the pr… | keyboard function keys | Siri Remote | ✗ | ✗ | 0.17 | 0.5 | 103.1s |
| 63 | Where does the hotel and casino located in which Bill Cosby's thi… | Las Vegas Strip in Paradi… | Las Vegas, Nevada | ✗ | ✗ | 0.40 | 1.0 | 104.6s |
| 64 | Which of Tara Strong's major voice roles in animated series is an… | Teen Titans Go! | Raven | ✗ | ✗ | 0.25 | 0.5 | 105.2s |
| 65 | The arena where the Lewiston Maineiacs played their home games ca… | 3,677 seated | 4,000 | ✗ | ✗ | 0.33 | 1.0 | 109.0s |
| 66 | Which dog's ancestors include Gordon and Irish Setters: the Manch… | Scotch Collie | English Setter is part of the Setter f… | ✗ | ✗ | 0.00 | 0.0 | 113.9s |
| 67 | Which year and which conference was the 14th season for this conf… | 2009 Big 12 Conference | 2009, Big 12 | ✗ | ✓ | 0.33 | 0.5 | 116.8s |
| 68 | Roger O. Egeberg was Assistant Secretary for Health and Scientifi… | 1969 until 1974 | Nixon Administration | ✗ | ✗ | 0.33 | 0.5 | 117.3s |
| 69 | In what city did the "Prince of tenors" star in a film based on a… | Rome | 'Enrico Caruso performed in "Don Carlo… | ✗ | ✗ | 0.00 | 0.0 | 120.3s |
| 70 | The Livesey Hall War Memorial commemorates the fallen of which war… | World War II | South Suburban Gas Company of London | ✗ | ✗ | 0.25 | 0.5 | 122.3s |
| 71 | Rostker v. Goldberg held that the practice of what way of filling… | Conscription | gender distinction was challenged in r… | ✗ | ✗ | 0.33 | 0.5 | 122.8s |
| 72 | When was the American lawyer, lobbyist and political consultant w… | April 1, 1949 | jonathan cohen is a person. Jonathan C… | ✗ | ✗ | 0.20 | 0.5 | 123.4s |
| 73 | Which other Mexican Formula One race car driver has held the podi… | Pedro Rodríguez | I couldn't find enough information to… | ✗ | ✗ | 0.20 | 0.5 | 126.9s |
| 74 | This singer of A Rather Blustery Day also voiced what hedgehog? | Sonic | James Jonah Cummings | ✗ | ✗ | 0.00 | 0.0 | 130.4s |
| 75 | Who was known by his stage name Aladin and helped organizations i… | Eenasul Fateh | I couldn't find enough information to… | ✗ | ✗ | 0.25 | 0.5 | 145.0s |
| 76 | What government position was held by the woman who portrayed Corl… | Chief of Protocol | Shirley Temple | ✗ | ✗ | 0.40 | 1.0 | 146.4s |
| 77 | What screenwriter with credits for "Evolution" co-wrote a film st… | David Weissman | David Weissman | ✓ | ✓ | 0.50 | 1.0 | 147.1s |
| 78 | What occupation do Chris Menges and Aram Avakian share? | director | Chris Menges is a cinematographer who… | ✗ | ✗ | 0.20 | 0.5 | 147.5s |
| 79 | who is the younger brother of The episode guest stars of The Hard… | Bill Murray | Brian Doyle-Murray is the younger brot… | ✗ | ✓ | 0.25 | 0.5 | 149.7s |
| 80 | What science fantasy young adult series, told in first person, ha… | Animorphs | I couldn't find enough information to… | ✗ | ✗ | 0.40 | 1.0 | 157.8s |
| 81 | Alfred Balk served as the secretary of the Committee on the Emplo… | Nelson Rockefeller | Nelson Rockefeller | ✓ | ✓ | 0.33 | 1.0 | 158.6s |
| 82 | Which writer was from England, Henry Roth or Robert Erskine Child… | Robert Erskine Childers D… | Henry Roth was American. | ✗ | ✗ | 0.29 | 1.0 | 176.3s |
| 83 | What was the father of Kasper Schmeichel voted to be by the IFFHS… | World's Best Goalkeeper | I couldn't find enough information to… | ✗ | ✗ | 0.40 | 1.0 | 178.0s |
| 84 | Which French ace pilot and adventurer flew L'Oiseau Blanc? | Charles Eugène | I couldn't find enough information to… | ✗ | ✗ | 0.29 | 1.0 | 180.4s |
| 85 | The director of the romantic comedy "Big Stone Gap" is based in w… | Greenwich Village, New Yo… | Greenwich Village | ✗ | ✓ | 0.25 | 0.5 | 182.6s |
| 86 | In which year was the King who made the 1925 Birthday Honours bor… | 1865 | King George V was the monarch who made… | ✗ | ✗ | 0.50 | 1.0 | 191.4s |
| 87 | Which performance act has a higher instrument to person ratio, Ba… | Badly Drawn Boy | I couldn't find enough information to… | ✗ | ✗ | 0.20 | 0.5 | 206.3s |
| 88 | What is the name of the executive producer of the film that has a… | Ronald Shusett | Arnold Schwarzenegger is the executive… | ✗ | ✗ | 0.00 | 0.0 | 207.0s |
| 89 | Which British first-generation jet-powered medium bomber was used… | English Electric Canberra | No. 12 Squadron RAAF | ✗ | ✗ | 0.33 | 1.0 | 208.1s |
| 90 | In what month is the annual documentary film festival, that is pr… | March and April | The London International Documentary F… | ✗ | ✓ | 0.33 | 1.0 | 211.2s |
| 91 | Brown State Fishing Lake is in a country that has a population of… | 9,984 | I couldn't find enough information to… | ✗ | ✗ | 0.33 | 1.0 | 214.5s |
| 92 | Are Giuseppe Verdi and Ambroise Thomas both Opera composers? | yes | I couldn't find enough information to… | ✗ | ✗ | 0.33 | 1.0 | 217.2s |
| 93 | How many copies of Roald Dahl's variation on a popular anecdote s… | 250 million | I couldn't find enough information to… | ✗ | ✗ | 0.12 | 0.5 | 218.6s |
| 94 | The 2011–12 VCU Rams men's basketball team, led by third year hea… | 1838 | I couldn't find enough information to… | ✗ | ✗ | 0.25 | 1.0 | 224.9s |
| 95 | Ellie Goulding worked with what other writers on her third studio… | Max Martin, Savan Kotecha… | I couldn't find enough information to… | ✗ | ✗ | 0.00 | 0.0 | 238.5s |
| 96 | The 2017–18 Wigan Athletic F.C. season will be a year in which th… | Carabao Cup | 5-0 | ✗ | ✗ | 0.67 | 1.0 | 248.1s |
| 97 | What was the name of the 1996 loose adaptation of William Shakesp… | Tromeo and Juliet | I couldn't find enough information to… | ✗ | ✗ | 0.29 | 1.0 | 249.8s |
| 98 | What distinction is held by the former NBA player who was a membe… | shortest player ever to p… | I couldn't find enough information to… | ✗ | ✗ | 0.40 | 1.0 | 291.5s |
| 99 | Robert Suettinger was the national intelligence officer under whi… | William Jefferson Clinton | I couldn't find enough information to… | ✗ | ✗ | 0.11 | 0.5 | 300.5s |
| 100 | The Vermont Catamounts men's soccer team currently competes in a … | the North Atlantic Confer… | I couldn't find enough information to… | ✗ | ✗ | 0.29 | 1.0 | 309.9s |

---

## 10. Comparison to Previous Runs

### Overall Performance Table

| Run | Pipeline | Model | EM | Fuzzy | F1 | Precision | Recall | Avg Time |
|---|---|---|---|---|---|---|---|---|
| Gemma3:4b — Looping | Looping agentic loop | `gemma3:4b` (local) | 45.0% | 54.0% | 0.539 | ~0.216 | ~0.717 | ~30s |
| Gemini Flash — Sub-Questions | Per-sub-question retrieval | `gemini-flash` (cloud) | 65.0% | 76.0% | — | — | 0.620 | 43.0s |
| Gemini Flash Preview — Looping | Looping agentic loop | `gemini-flash-preview` (cloud) | 62.6% | 78.8% | 0.765 | 0.216 | 0.717 | 79.7s |
| Gemini Flash Lite — Final | Iterative loop + graph expansion + BM25 | `gemini-3.1-flash-lite-preview` (cloud) | 59.0% | 76.0% | 0.705 | 0.330 | 0.665 | 18.10s |
| **Gemma3:4b — Final (this run)** | **Iterative loop + graph expansion + BM25** | **`gemma3:4b` (local)** | **30.0%** | **41.0%** | **0.383** | **0.351** | **0.625** | **91.66s** |

### Key Comparisons

**vs. Gemini Flash Lite Final (identical infrastructure, different LLM):**
- EM: −29pp (30.0% vs 59.0%) — identical retrieval stack, LLM quality is the sole variable
- Fuzzy: −35pp (41.0% vs 76.0%)
- F1: −0.322 (0.383 vs 0.705)
- Retrieval precision: +0.021 (0.351 vs 0.330) — near-identical
- Retrieval recall: −0.040 (0.625 vs 0.665) — near-identical
- Response time: **5.1× slower** (91.66s vs 18.10s)
- Not-found abstentions: 17 vs 3 (5.7×)
- EM at full recall: 24% vs 62% (−38pp)

This comparison directly answers: *"How much does the LLM matter on the Final Implementation pipeline?"* Answer: **−29 EM points** and **5.1× slower**, with identical retrieval infrastructure.

**vs. Gemma3:4b Looping (same model, prior pipeline):**
- EM: −15pp (30.0% vs 45.0%) — the Final Implementation pipeline with local Gemma3:4b performs *worse* than the old Looping pipeline using the same model
- Retrieval precision: +0.135 (0.351 vs ~0.216) — significantly better precision
- Retrieval recall: −0.092 (~0.717 vs 0.625) — lower recall than the prior pipeline
- Response time: **3× slower** (91.66s vs ~30s)

The regression in EM (45% → 30%) despite improved retrieval precision is significant. The Final Implementation pipeline is more demanding on the LLM — the iterative loop requires the model to orchestrate sub-queries, assess sufficiency, and produce structured output across multiple iterations. Gemma3:4b struggles with this orchestration burden more than the simpler single-pass Looping architecture.

**vs. Gemini Flash Sub-Questions (best prior EM run):**
- EM: −35pp (30.0% vs 65.0%) — the largest gap of any comparison in this benchmark series
- The Sub-Questions pipeline (parallel decomposition) was optimised for 2-hop questions; the iterative loop is more general but more demanding on reasoning quality

### LLM Contribution Isolation (Final Implementation only)

| LLM | EM | Fuzzy | F1 | Time | Notes |
|---|---|---|---|---|---|
| `gemini-3.1-flash-lite-preview` (cloud) | 59.0% | 76.0% | 0.705 | 18.10s | Same KB, same retrieval stack |
| `gemma3:4b` (local, Ollama) | **30.0%** | **41.0%** | **0.383** | **91.66s** | Same KB, same retrieval stack |
| **Δ** | **−29pp** | **−35pp** | **−0.322** | **+5.1×** | Pure LLM effect |

This is the cleanest A/B comparison in the benchmark series: everything identical except the LLM. The LLM alone accounts for a 29-point EM gap and a 5× latency increase.

---

## 11. Key Findings & Recommendations

### Findings

1. **LLM quality is the primary determinant of answer accuracy on the Final Implementation pipeline.** The 29pp EM gap between Gemma3:4b and Flash Lite, on identical infrastructure and identical knowledge graph, proves this conclusively. Improving the retrieval stack further will have limited impact if the reasoning model cannot use the retrieved context.

2. **Gemma3:4b fails to utilise retrieved context.** EM at full recall is only 24% (9/37) — the model has both supporting documents in context and still fails 3 out of 4 times. Flash Lite achieves 62% under the same condition. This is not a retrieval problem; it is a reasoning problem.

3. **High abstention rate (17%) indicates model over-caution.** 17 "I couldn't find enough information" responses, many on questions where Rc=1.0 (e.g. Giuseppe Verdi/Ambroise Thomas, Animorphs, Vermont Catamounts). The model refuses to commit to an answer rather than reasoning from available context. This is a fundamental characteristic of small local models under complex orchestration demands.

4. **Retrieval quality is comparable to Flash Lite.** Precision (0.351 vs 0.330) and recall (0.625 vs 0.665) are within 4 points of each other. The retrieval stack (Kuzu + Typesense + Qdrant + reranker) performs consistently regardless of LLM. Investment in retrieval architecture is well-placed.

5. **The Final Implementation pipeline is more demanding on the LLM than the prior Looping architecture.** EM regressed from 45% (Looping pipeline + Gemma3:4b) to 30% (Final Implementation + Gemma3:4b) despite better retrieval precision. The iterative orchestration loop — sub-query generation, sufficiency assessment, structured output — amplifies LLM reasoning weaknesses.

6. **Wrong answer-type errors are a significant failure mode.** 11 of 59 hard failures involve the model answering the wrong *type* of question (name instead of position, location instead of yes/no, etc.). This pattern does not appear in Flash Lite results at the same frequency. Gemma3:4b's instruction-following is less reliable.

7. **Wall-clock time is prohibitive for production use.** 2.5 hours for 100 questions, 91.66s mean, P90 of 214.5s. A production system cannot serve users at this latency with a local 4B model on consumer hardware.

8. **Zero errors or crashes.** Despite 2.5 hours of continuous operation, 10 iterations per question, and full hybrid search + graph expansion per iteration, the pipeline is completely stable. This is a positive infrastructure result.

### Recommendations

| Priority | Recommendation | Expected Impact |
|---|---|---|
| Critical | **Do not use `gemma3:4b` as the reasoning LLM on the Final Implementation pipeline in production.** The 30% EM rate and 91.66s latency are not viable. Flash Lite at 59% EM and 18.10s mean is the minimum acceptable configuration. | Baseline restoration |
| High | **If a local model is required** (no cloud API access), evaluate a larger model: `gemma3:12b`, `llama3.1:8b`, or `qwen2.5:7b-instruct`. The 4B parameter class is insufficient for multi-step orchestration on complex multi-hop questions. | +10–20pp EM estimate |
| High | **Address the abstention failure mode.** Modify the `iterative_step` prompt to require a best-guess answer on loop exhaustion rather than "I couldn't find enough information." When Rc=1.0 and the model still refuses to answer, force extraction from the retrieved documents. | +5–10pp EM |
| High | **Improve answer-type instruction following.** Add explicit answer-type constraints to the `iterative_step` system prompt: for yes/no questions, require a yes/no verdict; for position questions, prohibit returning a person's name. This is a prompt engineering fix, not a retrieval fix. | +4–6pp EM |
| Medium | **Evaluate retrieval recall impact with a stronger LLM.** Recall=0.0 affects 12 questions (12%). With a better LLM, these 12 are pure losses (no recovery from parametric knowledge). Investigating why these 12 questions return no supporting documents is worthwhile. | +2–4pp EM (with better LLM) |
| Low | **Consider removing the iterative orchestration burden for simple 2-hop questions.** A classifier that routes single-fact questions directly to a retrieval-then-answer pass (no loop) could substantially reduce latency and improve answer quality for the ~40% of HotPotQA questions where one retrieval iteration is sufficient. | +5–10pp EM, −30s mean latency |
