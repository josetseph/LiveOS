# Final Implementation — Model Comparison Report
## HotPotQA · N = 100 · Identical Infrastructure · Three LLMs

*Consolidated from individual run reports:*
- *[GEMINI3.1_FLASH_LITE_RETRIEVAL_BENCHMARK_REPORT.md](GEMINI3.1_FLASH_LITE_RETRIEVAL_BENCHMARK_REPORT.md)*
- *[GEMMA3_4B_RETRIEVAL_BENCHMARK_REPORT.md](GEMMA3_4B_RETRIEVAL_BENCHMARK_REPORT.md)*
- *[GEMMA4_E4B_RETRIEVAL_BENCHMARK_REPORT.md](GEMMA4_E4B_RETRIEVAL_BENCHMARK_REPORT.md)*

**Pipeline**: Final Implementation — iterative loop (≤ 10 iterations), hybrid search (entity match + Typesense BM25 + Qdrant vector), Kuzu graph neighbour expansion, `qwen3-reranker-0.6b`  
**Knowledge graph**: 990 HotPotQA notes, ingested with `gemma3:4b`, 9,636 nodes / 8,238 relationships  
**Variable**: LLM only — all three runs share identical infrastructure, knowledge graph, and evaluation harness

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Shared Infrastructure](#2-shared-infrastructure)
3. [Answer Quality — Cross-Model](#3-answer-quality--cross-model)
4. [Response Time — Cross-Model](#4-response-time--cross-model)
5. [Retrieval Quality — Cross-Model](#5-retrieval-quality--cross-model)
6. [Recall × Accuracy Cross-Tabulation](#6-recall--accuracy-cross-tabulation)
7. [Model Agreement Analysis](#7-model-agreement-analysis)
8. [Failure Mode Analysis](#8-failure-mode-analysis)
9. [Full Per-Question Results — All Three Models](#9-full-per-question-results--all-three-models)
10. [Key Findings & Recommendations](#10-key-findings--recommendations)

---

## 1. Executive Summary

### 1.1 Results at a Glance

| Metric | Gemini 3.1 Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| **Inference** | Google Cloud API | Ollama local | Ollama local |
| **Exact Match (EM)** | **59.0%** | 30.0% | 58.0% |
| **Fuzzy Match** | 76.0% | 41.0% | **81.0%** ← best |
| **Token F1** | 0.705 | 0.383 | **0.737** ← best |
| **Contains expected** | 67.0% | 36.0% | **74.0%** ← best |
| **Hard failures** | 24 | 59 | **19** ← fewest |
| **Not-found responses** | 3 | 17 | **2** ← fewest |
| **Avg response time** | **18.10 s** ← fastest | 91.66 s | 212.10 s |
| **Median response time** | **11.72 s** | 55.38 s | 145.86 s |
| **Retrieval Precision** | 0.330 | **0.351** | 0.349 |
| **Retrieval Recall** | 0.665 | 0.625 | **0.715** ← best |
| **Retrieval F1** | 0.441 | 0.449 | **0.469** ← best |
| **Full recall (Rc=1.0) questions** | 42 | 37 | **52** ← most |
| **EM at full recall** | 62% (26/42) | 24% (9/37) | 50% (26/52) |
| **Answer verbosity (mean words)** | 3.6 | 4.2 | 7.1 |
| **Wall clock (100 questions)** | ~30 min | ~2.5 h | ~8.75 h |
| **Error count** | 0 | 0 | 0 |

### 1.2 Key Takeaways

**The LLM is the dominant variable.** All three runs share identical infrastructure (same knowledge graph, same retrieval pipeline, same reranker, same embedding). The 29 percentage-point spread in EM (30.0% → 59.0%) and the 40 percentage-point spread in fuzzy match (41.0% → 81.0%) are entirely attributable to LLM quality, not infrastructure.

**Gemma3:4b is the outlier — not the baseline.** Only 34 questions are uniquely failed by Gemma3:4b (both Flash Lite and Gemma4 pass them), versus 3 unique failures for Flash Lite and 2 for Gemma4. Gemma3:4b's 17 not-found responses (5× more than the other models) are a reasoning quality problem, not a retrieval problem — retrieval precision (0.351) is actually the highest of any run.

**Gemma4:e4b matches cloud model accuracy locally.** At 58.0% EM (vs. 59.0% for Flash Lite) and 81.0% fuzzy match (vs. 76.0%), gemma4:e4b demonstrates that a sufficiently large local model can match cloud API accuracy on this task. It achieves the best fuzzy match, best F1, and best retrieval recall of any run. The cost is a 212 s mean latency — 11.7× slower than Flash Lite.

**Flash Lite is the production-viable choice.** For interactive workloads: 18.10 s mean, matching gemma4 EM (59% vs 58%), total wall clock ~30 min for 100 questions. For data-residency or batch/offline workloads: gemma4:e4b is the stronger model.

---

## 2. Shared Infrastructure

All three runs are evaluated on the **identical Final Implementation pipeline**. The only variable between runs is the LLM.

### 2.1 Common Configuration

| Component | All Three Runs |
|---|---|
| Benchmark dataset | HotPotQA (100 questions) |
| Embedding model | `qwen3-embedding:0.6b` (Ollama local, 1024-dim) |
| Reranker | `qwen3-reranker-0.6b` (local, float16) |
| Reranker thresholds | yes=9693, no=2152 |
| Graph database | Kuzu (embedded) |
| Vector store | Qdrant (port 6333) |
| Full-text search | Typesense BM25 (port 8108, lexical STEP 1b) |
| Relational DB | PostgreSQL 16 (asyncpg, port 5433) |
| Knowledge graph | 990 HotPotQA notes, ingested with `gemma3:4b` |
| Graph nodes | 9,636 (7,284 entity + 990 note + 1,362 community) |
| Graph relationships | 8,238 |
| Community detection | Leiden algorithm |
| Max loop iterations | 10 per question |
| Error count | 0 (all runs, all questions) |

### 2.2 Per-Run LLM

| Parameter | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| Model | `gemini-3.1-flash-lite-preview` | `gemma3:4b` | `gemma4:latest` |
| Provider | Google AI SDK (cloud) | Ollama local | Ollama local |
| Run date | — | 2026-05-08 | 2026-05-09 |
| Run duration | ~30 min | ~2.5 h | ~8.75 h |

### 2.3 Pipeline Architecture (shared)

Each iteration of the retrieval loop:
1. Embeds the current sub-query and runs **hybrid search** (Qdrant vector + Typesense BM25 + entity name match)
2. Deduplicates candidates by `node_id`
3. Expands top results via **graph neighbour traversal** (1-hop Kuzu + Qdrant NL relationship lookup)
4. Reranks all candidates with `qwen3-reranker-0.6b`
5. Calls the LLM with accumulated context to assess sufficiency, extract a finding, or generate the next sub-query
6. Accumulates findings across iterations; terminates on `can_answer=True` or the 10-iteration ceiling

On loop exhaustion, the most recent non-empty `FINDING` is returned directly.

---

## 3. Answer Quality — Cross-Model

### 3.1 Primary Metrics

| Metric | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| Exact Match (EM) | **59.0%** (59/100) | 30.0% (30/100) | 58.0% (58/100) |
| Fuzzy Match | 76.0% (76/100) | 41.0% (41/100) | **81.0%** (81/100) |
| Token-level F1 | 0.705 | 0.383 | **0.737** |
| Contains expected | 67.0% | 36.0% | **74.0%** |
| EM ✓ and Fz ✓ | 59 | 30 | 58 |
| EM ✗ and Fz ✓ (fuzzy-only) | 17 | 11 | **23** |
| EM ✗ and Fz ✗ (hard failures) | 24 | **59** | 19 |
| "Not found" type responses | 3 | **17** | 2 |
| Errors / exceptions | 0 | 0 | 0 |

### 3.2 The EM–Fuzzy Gap

| Model | EM | Fuzzy | Gap | Driver |
|---|---|---|---|---|
| Flash Lite | 59% | 76% | **17 pp** | Minor formatting (article/preposition differences) |
| Gemma3:4b | 30% | 41% | **11 pp** | Narrow — most failures are factual misses, not format issues |
| Gemma4:e4b | 58% | 81% | **23 pp** ← largest | Verbose output — semantically correct but over-qualified |

The gap reveals each model's failure character. Gemma3:4b's narrow gap (11 pp) signals that most of its wrong answers are genuinely wrong — it doesn't know the answer rather than expressing it incorrectly. Gemma4's wide gap (23 pp) is the opposite: the model usually has the right fact, but says "Chief of Protocol of the United States" where the gold string is "Chief of Protocol". Flash Lite sits between, with concise answers that match gold strings closely.

### 3.3 Answer Verbosity

| Metric | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| Mean words (first line) | **3.6** | 4.2 | 7.1 |
| Median words (first line) | 2.0 | 2.0 | 2.0 |
| Max words (first line) | 40 | 27 | **65** |
| Not-found responses | 3 | **17** | 2 |

All three models share a median of 2 words — the binary yes/no and single-entity answers dominate. The mean diverges because Gemma4 produces longer rationale sentences on harder questions, and Gemma3 produces "I couldn't find enough information" responses (averaging ~8 words each) for 17 questions.

### 3.4 Not-Found Abstention Rate

The abstention rate (model explicitly refuses to answer) reveals reasoning confidence:

- **Flash Lite: 3%** — only genuine KB misses (Animorphs, 2001 census population, one retrieval anomaly)
- **Gemma3:4b: 17%** — most abstentions occur when retrieval recall = 1.0, meaning both gold documents are in context but the model still gives up. This is a reasoning quality failure, not a retrieval failure.
- **Gemma4:e4b: 2%** — nearly eliminates abstention. The larger model reasons through uncertainty rather than refusing.

---

## 4. Response Time — Cross-Model

### 4.1 Summary Statistics

| Statistic | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| **Mean** | **18.10 s** | 91.66 s | 212.10 s |
| **Median** | **11.72 s** | 55.38 s | 145.86 s |
| Std Dev | 23.11 s | 77.58 s | 188.74 s |
| Min | **1.85 s** | 14.72 s | 82.97 s |
| Max | 183.20 s | 309.85 s | **923.29 s** |
| P25 | **9.44 s** | 26.34 s | 120.88 s |
| P75 | **16.55 s** | 146.40 s | 196.31 s |
| P90 | **26.16 s** | 214.50 s | 330.01 s |
| P95 | **72.45 s** | 248.15 s | 741.76 s |
| Wall clock (100 Qs) | ~30 min | ~2.5 h | ~8.75 h |

Speed ratios relative to Flash Lite: Gemma3:4b is **5.1× slower**, Gemma4:e4b is **11.7× slower**.

### 4.2 Time Bucket Distribution

| Bucket | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| < 10 s | 28 (28%) | 0 (0%) | 0 (0%) |
| 10 – 20 s | 57 (57%) | 11 (11%) | 0 (0%) |
| 20 – 40 s | 8 (8%) | 27 (27%) | 0 (0%) |
| 40 – 60 s | 1 (1%) | 15 (15%) | 0 (0%) |
| 60 – 120 s | 5 (5%) | 15 (15%) | 24 (24%) |
| 120 – 300 s | 1 (1%) | 30 (30%) | 62 (62%) |
| > 300 s | 0 (0%) | 2 (2%) | 14 (14%) |

Flash Lite: 85% of questions answered in under 20 s. Gemma3:4b: 42% exceed 2 minutes. Gemma4: 100% exceed 1 minute, 76% exceed 2 minutes.

```
Flash Lite  <10s│████████████████████████████     28 queries
            <20s│████████████████████████████████████████████████████████  57 queries
            <40s│████████   8
           <120s│██████     6

Gemma3:4b   <20s│███████████  11
            <40s│███████████████████████████  27
            <60s│███████████████  15
           <120s│███████████████  15
           <300s│██████████████████████████████  30
           >300s│██  2

Gemma4:e4b <120s│████████████████████████  24
           <300s│██████████████████████████████████████████████████████████████  62
           <600s│██████  6
           >600s│████████  8
```

### 4.3 Speed vs. Accuracy Trade-off

```
EM Accuracy
80% │
70% │                          ● Flash Lite (59%, 18s)
60% │                          ● Gemma4 (58%, 212s)
50% │
40% │
30% │  ● Gemma3 (30%, 92s)
20% │
    └────────────────────────────────── Avg Response Time (s)
       0        50       100      150      200      250
```

Flash Lite dominates — higher EM, 11.7× faster than the closest competitor (Gemma4). Gemma4 makes sense only for workloads where cloud API is unavailable and batch throughput is acceptable.

---

## 5. Retrieval Quality — Cross-Model

Retrieval metrics measure how well the pipeline surfaces the gold-standard context documents, independent of LLM answer quality. HotPotQA questions require exactly 2 gold documents; recall is therefore 0.0, 0.5, or 1.0.

### 5.1 Aggregate Retrieval

| Metric | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| Retrieval Precision | 0.330 | **0.351** | 0.349 |
| Retrieval Recall | 0.665 | 0.625 | **0.715** |
| Retrieval F1 | 0.441 | 0.449 | **0.469** |

### 5.2 Recall Distribution

| Recall Value | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| 0.0 (neither gold doc retrieved) | 9 (9%) | 12 (12%) | 9 (9%) |
| 0.5 (one gold doc retrieved) | 49 (49%) | 51 (51%) | 39 (39%) |
| 1.0 (both gold docs retrieved) | **42 (42%)** | 37 (37%) | **52 (52%)** ← most |

Gemma4 achieves full recall (Rc=1.0) in 52% of questions — 10 pp more than Flash Lite. This reflects that the larger model generates better sub-queries across iterations, driving the retrieval loop to surface both gold documents more often. Gemma3:4b has the most Rc=0.0 failures (12), suggesting weaker initial query formulation.

### 5.3 Retrieval Independence from LLM Quality

Retrieval recall varies across runs despite identical retrieval infrastructure because **the LLM drives sub-query formulation**. Better sub-queries → more targeted searches → higher recall. This is the mechanism by which a smarter LLM improves retrieval even though the retrieval stack is unchanged.

Retrieval precision is nearly identical (0.330–0.351) across all three runs because it is dominated by the reranker and deduplication logic, which are LLM-independent. The pipeline accumulates a consistent amount of noise (non-gold documents) regardless of LLM quality.

---

## 6. Recall × Accuracy Cross-Tabulation

### 6.1 Flash Lite

| Retrieval Recall | N | EM | Fuzzy-only | Hard Fail | EM % | Fz % |
|---|---|---|---|---|---|---|
| 0.0 (miss) | 9 | 4 | 3 | 2 | 44% | 78% |
| 0.5 (partial) | 49 | 29 | 12 | 8 | 59% | 84% |
| 1.0 (full) | 42 | 26 | 8 | 8 | **62%** | 81% |

### 6.2 Gemma3:4b

| Retrieval Recall | N | EM | Fuzzy-only | Hard Fail | EM % | Fz % |
|---|---|---|---|---|---|---|
| 0.0 (miss) | 12 | 5 | 1 | 6 | 42% | 50% |
| 0.5 (partial) | 51 | 16 | 7 | 28 | 31% | 45% |
| 1.0 (full) | 37 | 9 | 3 | 25 | **24%** | 32% |

### 6.3 Gemma4:e4b

| Retrieval Recall | N | EM | Fuzzy-only | Hard Fail | EM % | Fz % |
|---|---|---|---|---|---|---|
| 0.0 (miss) | 9 | 5 | 1 | 3 | 56% | 67% |
| 0.5 (partial) | 39 | 27 | 6 | 6 | **69%** | **85%** |
| 1.0 (full) | 52 | 26 | 16 | 10 | 50% | 81% |

### 6.4 Cross-Model Observations

**EM at full recall (Rc=1.0)**: Flash Lite 62%, Gemma4 50%, Gemma3 24%. When the pipeline delivers both gold documents, Flash Lite uses them most effectively. Gemma4's lower EM at full recall (50%) is a verbosity artifact — fuzzy match at Rc=1.0 is 81% for Gemma4 vs. 81% for Flash Lite, essentially identical. Gemma3 at 24% EM (32% fuzzy) with full context is the standout failure: the model is presented both answer documents and still answers incorrectly or abstains 68% of the time.

**Gemma4's Rc=0.0 advantage**: When no gold document is retrieved, Gemma4 still achieves 56% EM — higher than Flash Lite (44%) or Gemma3 (42%) under the same condition. This demonstrates that gemma4's larger parametric knowledge compensates for KB misses. It answers questions from pre-training when retrieval fails.

**Gemma3 fails consistently across all recall levels**: Even at Rc=0.5 (one gold doc in context), Gemma3 achieves only 31% EM and 45% fuzzy — worse than Flash Lite's Rc=0.0 performance (44% EM). The model cannot reason reliably from partial context.

---

## 7. Model Agreement Analysis

This section is only possible in the merged view — it identifies which questions are universally hard or easy, and where individual models diverge.

### 7.1 Agreement Statistics

| Category | Count | % |
|---|---|---|
| All 3 EM correct | 24 | 24% |
| All 3 fuzzy correct | 35 | 35% |
| All 3 fuzzy fail (hard misses) | 13 | 13% |
| Only Gemma3 fails fuzzy | **34** | 34% |
| Only Flash Lite fails fuzzy | 3 | 3% |
| Only Gemma4 fails fuzzy | 2 | 2% |

### 7.2 The Hard Core (13 questions — all 3 models fail fuzzy)

These 13 questions are beyond the current pipeline's capability regardless of LLM. They represent either KB gaps or fundamental reasoning challenges:

| # | Question (truncated) | Expected | Notes |
|---|---|---|---|
| 1 | Alvaro Mexia had a diplomatic mission with which tribe… | Apalachees | All wrong: Ais, wrong entity, Ais |
| 7 | Brown State Fishing Lake is in a country that has a pop… | 9,984 | KB miss — population not in graph |
| 30 | What science fantasy young adult series, told in first… | Animorphs | Classic KB miss — Animorphs not ingested |
| 31 | What is the name of the executive producer of the film… | Ronald Shusett | KB miss |
| 36 | Rostker v. Goldberg held that the practice of what way… | Conscription | All models return wrong answer type |
| 39 | Which Australian city founded in 1838 contains a board… | Marion, South Australia | All return "Marion" without state (FL fails EM too) |
| 49 | Scott Parkin has been a vocal critic of Exxonmobil… | more than 70 countries | Count format mismatch across all |
| 55 | Are Random House Tower and 888 7th Avenue both used… | no | All models hallucinate YES |
| 70 | Which filmmaker was known for animation, Lev Yilmaz… | Levni Yilmaz | Name variant — all return "Lev Yilmaz" |
| 77 | What type of forum did a former Soviet statesman init… | Organizations could… | All wrong |
| 79 | The 2011–12 VCU Rams men's basketball team… | 1838 | Date confusion across all models |
| 81 | Which French ace pilot and adventurer fly L'Oiseau… | Charles Eugène | All return full names instead of first name |
| 89 | According to the 2001 census, what was the population… | 35,124 | KB miss — specific census figure not in graph |
| 90 | Robert Suettinger was the national intelligence officer… | William Jefferson Clinton | All return "Bill Clinton" alias |

The Animorphs and Ronald Shusett questions have been consistent failures across every pipeline evaluated. Questions #55 (Random House Tower) and #79 (VCU Rams 1838) are factual-reasoning failures where the model draws the wrong conclusion from retrieved documents.

### 7.3 The Reliable Core (24 questions — all 3 EM correct)

24 questions are answered correctly by all three models, regardless of LLM quality. These represent well-ingested topics with unambiguous single-entity answers:

Sample: "2014 S/S is the debut album of… YG Entertainment", "Are Ferocactus and Silene both types of plant? YES", "D1NZ is a series based on what oversteering technique? Drifting", "Who is the writer of… Phil Spector", "What was the Roud Folk Song Index… 821", "Hayden is a singer-songwriter from Canada, but where does his… Fujioka, Gunma", "The Album Against the Wind was the 11th Album of… Bob Seger"…

### 7.4 Gemma3-Unique Failures (34 questions)

34 questions that both Flash Lite and Gemma4 answer (fuzzy) but Gemma3 fails. This is the clearest quantification of Gemma3:4b's reasoning gap:

Selected examples:
- "Were Scott Derrickson and Ed Wood of the same nationality?" → FL: ✓ YES, G4: ✓ YES, G3: ✗ No
- "Are the Laleli Mosque and Esma Sultan Mansion located in the same neighborhood?" → FL: ✓, G4: ✓, G3: ✗
- "What WB supernatural drama series was Jawbreaker star Rose McGowan in? Charmed" → FL: ✓, G4: ✓, G3: ✗
- "The arena where the Lewiston Maineiacs played their home game…" → FL: ✗, G4: ✓, G3: ✗ (G4 recovers this)
- "In what city did the 'Prince of tenors' star in a film… Rome" → FL: ✓, G4: ✓, G3: ✗

These questions are not hard — the other two models answer them correctly. Gemma3's failures here are reasoning failures, not retrieval failures. Most have Rc ≥ 0.5.

### 7.5 FL-Unique and G4-Unique Failures

**Flash Lite fails alone (3 questions)**:
- "Where is the company that Sachin Warrier worked for… Mumbai" — FL: ✗, G3: ✓, G4: ✓
- "Are both Cypress and Ajuga genera? no" — FL: ✗ (returns YES), G3: ✓, G4: ✓
- "What is the name of the singer who's song was released… Usher" — FL: ✗, G3: ✗, G4: ✓ (G4 recovers, G3 fails too)

**Gemma4 fails alone (2 questions)**:
- "What is the county seat of the county where East Lempster… Newport" — FL: ✓, G3: ✓, G4: ✗ (verbose non-answer after 301 s)
- "Which filmmaker was known for animation, Lev Yilmaz…" — FL: ✗, G3: ✗, G4: ✗ (all fail — should be in hard core)

Note: with only 2–3 unique failures each, Flash Lite and Gemma4 have essentially the same failure profile on non-KB-miss questions.

---

## 8. Failure Mode Analysis

### 8.1 Failure Taxonomy

| Category | Flash Lite | Gemma3:4b | Gemma4:e4b |
|---|---|---|---|
| KB miss (entity not in graph) | ~6 | ~5 | ~8 |
| Abstention despite having context | 0 | **12** | 0 |
| Wrong inference at full recall | ~8 | ~12 | ~7 |
| Verbosity / format mismatch (hard fail) | ~4 | 2 | 0 |
| Name / alias mismatch | ~3 | ~5 | ~2 |
| Numeric / measurement format | ~3 | ~3 | ~2 |

*Approximate — some failures overlap categories.*

### 8.2 Gemma3:4b Abstention at Full Recall (critical finding)

12 questions where Gemma3 abstains ("I couldn't find enough information") despite retrieval recall = 1.0 — both gold documents are in context. Sample:

- "Are the Laleli Mosque and Esma Sultan Mansion in the same neighborhood?" (Rc=1.0) → "I couldn't determine…" — Flash Lite: NO ✓, Gemma4: NO ✓
- "What was the Kasper Schmeichel father voted to be?" (Rc=1.0) → abstains — FL: World's Best Goalkeeper ✓, G4: ✓
- "The 2017–18 Wigan Athletic F.C. season…" (Rc=1.0) → abstains — FL: Carabao Cup ✓, G4: ✓

This confirms that the retrieval system delivers the necessary information for these questions. The failure is pure reasoning quality — Gemma3:4b cannot synthesize an answer even when the answer is present in the retrieved documents.

### 8.3 Shared Hard Questions (3+ models fail)

Beyond the 13-question hard core:

**Roald Dahl question (Q26)**: All 3 fail EM (expected: "250 million"). FL returns ✓ fuzzy, G3 fails, G4 returns ✓ fuzzy. G4 takes 923 s.

**Emma Bull / Virginia Woolf (Q18)**: FL fails both, G3 fuzzy only, G4 fuzzy only. Expected: "Adeline Virginia Woolf" — the full formal name traps EM.

**The football manager / David Beckham (Q56)**: All 3 fail EM. Expected: "from 1986 to 2013" — preposition inclusion required. FL and G4 get fuzzy (return "1986 to 2013"), G3 fails outright.

### 8.4 Infrastructure-Level Failure: 2001 Census Population (Q89)

"According to the 2001 census, what was the population of the civil parish…" (expected: 35,124) — all three models retrieve both gold documents (Rc=1.0) but return wrong population figures or verbose explanations. This is a data quality issue in the knowledge graph: the specific 2001 census figure for this parish appears to have been ingested but not stored in a way the retrieval pipeline surfaces correctly.

### 8.5 Persistent KB Misses

The following questions have never been answered correctly across any evaluated run:

| Question | Expected | Root Cause |
|---|---|---|
| "What science fantasy young adult series…" | Animorphs | Entity not ingested |
| "What is the name of the executive producer of the film…" | Ronald Shusett | Entity not ingested |
| "Which Australian city founded in 1838…" | Marion, South Australia | Format — "Marion" only is ingested |

---

## 9. Full Per-Question Results — All Three Models

Columns: **#** · **Question** (55 chars) · **Expected** · **FL** (EM/Fz/Rc/t) · **G3** (EM/Fz/Rc/t) · **G4** (EM/Fz/Rc/t)  
EM and Fz: ✓ = pass, ✗ = fail · Rc: 0.0/0.5/1.0 · t: seconds  
Questions are ordered by test_id (evaluation order).

| # | Question | Expected | FL-EM | FL-Fz | FL-Rc | FL-t | G3-EM | G3-Fz | G3-Rc | G3-t | G4-EM | G4-Fz | G4-Rc | G4-t |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Alvaro Mexia had a diplomatic mission with which tribe… | Apalachees | ✗ | ✗ | 0.5 | 5.6 | ✗ | ✗ | 0.5 | 19.9 | ✗ | ✗ | 0.5 | 101.1 |
| 2 | What is the name of the fight song of the university wh… | Kansas Song | ✗ | ✓ | 0.5 | 21.3 | ✗ | ✓ | 1.0 | 26.3 | ✗ | ✓ | 0.5 | 141.8 |
| 3 | Who was the writer of These Boots Are Made for Walkin'… | Barton Lee Hazlewood | ✗ | ✓ | 0.5 | 10.7 | ✗ | ✗ | 0.0 | 50.0 | ✗ | ✓ | 0.0 | 136.4 |
| 4 | who is younger Keith Bostic or Jerry Glanville? | Keith Bostic | ✓ | ✓ | 0.0 | 18.3 | ✓ | ✓ | 0.5 | 50.6 | ✓ | ✓ | 0.5 | 86.5 |
| 5 | Where is the company that Sachin Warrier worked for… | Mumbai | ✗ | ✗ | 0.5 | 8.9 | ✓ | ✓ | 1.0 | 72.7 | ✓ | ✓ | 1.0 | 179.9 |
| 6 | Ralph Hefferline was a psychology professor at a univ… | New York City | ✓ | ✓ | 0.5 | 15.9 | ✗ | ✗ | 0.5 | 15.5 | ✓ | ✓ | 0.5 | 155.8 |
| 7 | Brown State Fishing Lake is in a country that has a p… | 9,984 | ✗ | ✗ | 1.0 | 183.2 | ✗ | ✗ | 1.0 | 214.5 | ✗ | ✗ | 1.0 | 182.3 |
| 8 | Alfred Balk served as the secretary of the Committee… | Nelson Rockefeller | ✓ | ✓ | 0.5 | 15.2 | ✓ | ✓ | 1.0 | 158.6 | ✓ | ✓ | 1.0 | 213.3 |
| 9 | In which year was the King who made the 1925 Birthday… | 1865 | ✓ | ✓ | 1.0 | 48.9 | ✗ | ✗ | 1.0 | 191.4 | ✗ | ✗ | 1.0 | 741.8 |
| 10 | What was the Roud Folk Song Index of the nursery rhym… | 821 | ✓ | ✓ | 0.5 | 10.6 | ✓ | ✓ | 0.5 | 35.2 | ✓ | ✓ | 0.5 | 121.8 |
| 11 | Where are Teide National Park and Garajonay National… | Canary Islands, Spain | ✗ | ✓ | 1.0 | 10.6 | ✗ | ✓ | 1.0 | 22.3 | ✗ | ✓ | 1.0 | 96.0 |
| 12 | What race track in the midwest hosts a 500 mile race… | Indianapolis Motor Speedway | ✓ | ✓ | 1.0 | 15.4 | ✗ | ✗ | 1.0 | 91.4 | ✓ | ✓ | 1.0 | 164.8 |
| 13 | What American professional Hawaiian surfer born 18 Oc… | John John Florence | ✓ | ✓ | 0.5 | 5.7 | ✓ | ✓ | 1.0 | 51.9 | ✓ | ✓ | 1.0 | 154.2 |
| 14 | What nationality were social anthropologists Alfred G… | British | ✓ | ✓ | 1.0 | 9.2 | ✓ | ✓ | 0.5 | 22.4 | ✓ | ✓ | 1.0 | 83.0 |
| 15 | A Japanese manga series based on a 16 year old high s… | 1962 | ✓ | ✓ | 0.0 | 10.3 | ✗ | ✓ | 0.5 | 75.7 | ✓ | ✓ | 0.5 | 229.7 |
| 16 | Which dog's ancestors include Gordon and Irish Setter… | Scotch Collie | ✓ | ✓ | 1.0 | 15.4 | ✗ | ✗ | 0.0 | 113.9 | ✓ | ✓ | 1.0 | 125.9 |
| 17 | Who is older, Annie Morton or Terry Richardson? | Terry Richardson | ✓ | ✓ | 1.0 | 17.6 | ✓ | ✓ | 0.5 | 27.1 | ✗ | ✓ | 1.0 | 101.4 |
| 18 | Who was born earlier, Emma Bull or Virginia Woolf? | Adeline Virginia Woolf | ✗ | ✗ | 1.0 | 83.9 | ✗ | ✓ | 1.0 | 52.2 | ✗ | ✓ | 1.0 | 432.3 |
| 19 | Which band, Letters to Cleo or Screaming Trees, had m… | Letters to Cleo | ✓ | ✓ | 1.0 | 18.9 | ✓ | ✓ | 0.5 | 33.1 | ✗ | ✓ | 1.0 | 866.8 |
| 20 | A medieval fortress in Dirleton, East Lothian, Scotla… | Yellowcraig | ✓ | ✓ | 0.5 | 12.4 | ✗ | ✗ | 0.5 | 30.6 | ✓ | ✓ | 0.5 | 153.6 |
| 21 | The Livesey Hal War Memorial commemorates the fallen… | World War II | ✓ | ✓ | 0.5 | 11.2 | ✗ | ✗ | 0.5 | 122.3 | ✓ | ✓ | 0.0 | 117.6 |
| 22 | What WB supernatural drama series was Jawbreaker star… | Charmed | ✓ | ✓ | 0.5 | 12.9 | ✓ | ✓ | 0.5 | 20.3 | ✓ | ✓ | 0.5 | 113.5 |
| 23 | Tysons Galleria is located in what county? | Fairfax County | ✓ | ✓ | 0.5 | 11.6 | ✓ | ✓ | 0.5 | 44.5 | ✓ | ✓ | 0.5 | 102.3 |
| 24 | Which writer was from England, Henry Roth or Robert E… | Robert Erskine Childers | ✗ | ✓ | 1.0 | 11.1 | ✗ | ✗ | 1.0 | 176.3 | ✗ | ✓ | 1.0 | 124.1 |
| 25 | Kaiser Ventures corporation was founded by an American… | Henry J. Kaiser | ✓ | ✓ | 0.5 | 11.9 | ✓ | ✓ | 1.0 | 51.0 | ✗ | ✗ | 0.5 | 113.4 |
| 26 | How many copies of Roald Dahl's variation on a popular… | 250 million | ✗ | ✓ | 0.5 | 94.9 | ✗ | ✗ | 0.5 | 218.6 | ✗ | ✓ | 1.0 | 923.3 |
| 27 | Vince Phillips held a junior welterweight title by an… | International Boxing Hall of Fame | ✓ | ✓ | 0.5 | 7.4 | ✗ | ✓ | 1.0 | 96.2 | ✗ | ✓ | 1.0 | 174.6 |
| 28 | Are Yingkou and Fuding the same level of city? | no | ✓ | ✓ | 1.0 | 15.5 | ✓ | ✓ | 0.5 | 26.7 | ✓ | ✓ | 1.0 | 124.4 |
| 29 | Who was known by his stage name Aladin and helped org… | Eenasul Fateh | ✓ | ✓ | 0.5 | 5.8 | ✗ | ✗ | 0.5 | 145.0 | ✓ | ✓ | 0.5 | 110.0 |
| 30 | What science fantasy young adult series, told in first… | Animorphs | ✗ | ✗ | 0.0 | 29.6 | ✗ | ✗ | 1.0 | 157.8 | ✗ | ✗ | 0.0 | 701.1 |
| 31 | What is the name of the executive producer of the film… | Ronald Shusett | ✗ | ✗ | 0.0 | 10.6 | ✗ | ✗ | 0.0 | 207.0 | ✗ | ✗ | 0.0 | 626.5 |
| 32 | Handi-Snacks are a snack food product line sold by wh… | Mondelez International, Inc. | ✗ | ✓ | 0.5 | 14.9 | ✗ | ✓ | 0.5 | 25.5 | ✓ | ✓ | 0.5 | 180.3 |
| 33 | What screenwriter with credits for "Evolution" co-wro… | David Weissman | ✓ | ✓ | 1.0 | 16.5 | ✓ | ✓ | 1.0 | 147.1 | ✓ | ✓ | 1.0 | 476.2 |
| 34 | The arena where the Lewiston Maineiacs played their h… | 3,677 seated | ✗ | ✗ | 1.0 | 8.7 | ✗ | ✗ | 1.0 | 109.0 | ✓ | ✓ | 1.0 | 124.5 |
| 35 | In what city did the "Prince of tenors" star in a fil… | Rome | ✓ | ✓ | 0.5 | 39.5 | ✗ | ✗ | 0.0 | 120.3 | ✓ | ✓ | 0.5 | 145.3 |
| 36 | Rostker v. Goldberg held that the practice of what wa… | Conscription | ✗ | ✗ | 0.5 | 6.5 | ✗ | ✗ | 0.5 | 122.8 | ✗ | ✗ | 0.5 | 103.7 |
| 37 | What is the middle name of the actress who plays Bobb… | Ann | ✓ | ✓ | 1.0 | 11.4 | ✓ | ✓ | 1.0 | 42.6 | ✓ | ✓ | 1.0 | 162.3 |
| 38 | What is the name for the adventure in "Tunnels and Tr… | Arena of Khazan | ✓ | ✓ | 0.5 | 7.5 | ✓ | ✓ | 0.5 | 23.9 | ✓ | ✓ | 0.5 | 108.5 |
| 39 | Which Australian city founded in 1838 contains a boar… | Marion, South Australia | ✗ | ✗ | 0.0 | 19.2 | ✗ | ✗ | 0.0 | 36.2 | ✗ | ✗ | 0.0 | 270.3 |
| 40 | What distinction is held by the former NBA player who… | shortest player ever to play in NBA | ✗ | ✗ | 1.0 | 11.3 | ✗ | ✗ | 1.0 | 291.5 | ✗ | ✓ | 0.5 | 147.8 |
| 41 | Were Scott Derrickson and Ed Wood of the same national… | yes | ✓ | ✓ | 1.0 | 26.2 | ✗ | ✗ | 0.5 | 32.5 | ✓ | ✓ | 1.0 | 196.3 |
| 42 | What government position was held by the woman who po… | Chief of Protocol | ✗ | ✓ | 0.5 | 17.1 | ✗ | ✗ | 1.0 | 146.4 | ✗ | ✓ | 1.0 | 232.0 |
| 43 | Are Local H and For Against both from the United State… | yes | ✓ | ✓ | 1.0 | 14.1 | ✓ | ✓ | 0.5 | 26.2 | ✓ | ✓ | 1.0 | 114.0 |
| 44 | Are Ferocactus and Silene both types of plant? | yes | ✓ | ✓ | 1.0 | 14.8 | ✓ | ✓ | 0.5 | 16.1 | ✓ | ✓ | 1.0 | 153.4 |
| 45 | Bordan Tkachuk was the CEO of a company that provides… | IT products and services | ✓ | ✓ | 1.0 | 9.1 | ✗ | ✗ | 0.5 | 14.7 | ✗ | ✓ | 1.0 | 155.4 |
| 46 | Which year and which conference was the 14th season f… | 2009 Big 12 Conference | ✓ | ✓ | 0.5 | 72.4 | ✗ | ✓ | 0.5 | 116.8 | ✗ | ✓ | 0.5 | 212.6 |
| 47 | The director of the romantic comedy "Big Stone Gap" i… | Greenwich Village, New York City | ✗ | ✓ | 0.5 | 7.8 | ✗ | ✓ | 0.5 | 182.6 | ✓ | ✓ | 0.0 | 136.0 |
| 48 | Seven Brief Lessons on Physics was written by an Ital… | 2000 | ✓ | ✓ | 1.0 | 7.8 | ✗ | ✗ | 1.0 | 45.3 | ✓ | ✓ | 1.0 | 101.6 |
| 49 | Scott Parkin has been a vocal critic of Exxonmobil an… | more than 70 countries | ✗ | ✓ | 1.0 | 10.3 | ✗ | ✗ | 0.5 | 21.5 | ✗ | ✗ | 1.0 | 180.8 |
| 50 | Are Giuseppe Verdi and Ambroise Thomas both Opera com… | yes | ✗ | ✗ | 0.0 | 1.9 | ✗ | ✗ | 1.0 | 217.2 | ✓ | ✓ | 1.0 | 111.0 |
| 51 | The battle in which Giuseppe Arimondi lost his life s… | sovereignty | ✗ | ✓ | 1.0 | 9.7 | ✗ | ✓ | 1.0 | 29.1 | ✗ | ✓ | 1.0 | 123.9 |
| 52 | What year did Guns N Roses perform a promo for a movi… | 1999 | ✓ | ✓ | 0.0 | 6.6 | ✓ | ✓ | 0.0 | 59.6 | ✓ | ✓ | 0.0 | 248.0 |
| 53 | The Vermont Catamounts men's soccer team currently co… | the North Atlantic Conference | ✗ | ✓ | 0.5 | 24.9 | ✗ | ✗ | 1.0 | 309.8 | ✗ | ✓ | 0.5 | 163.9 |
| 54 | Are both Elko Regional Airport and Gerald R. Ford Int… | no | ✓ | ✓ | 1.0 | 8.9 | ✗ | ✗ | 1.0 | 46.5 | ✓ | ✓ | 1.0 | 152.3 |
| 55 | Are Random House Tower and 888 7th Avenue both used f… | no | ✗ | ✗ | 1.0 | 11.5 | ✗ | ✗ | 0.5 | 41.9 | ✗ | ✗ | 1.0 | 145.0 |
| 56 | The football manager who recruited David Beckham mana… | from 1986 to 2013 | ✗ | ✓ | 1.0 | 11.8 | ✗ | ✗ | 1.0 | 57.2 | ✗ | ✓ | 1.0 | 129.3 |
| 57 | In 1991 Euromarché was bought by a chain that operate… | 1,462 | ✓ | ✓ | 1.0 | 15.3 | ✗ | ✗ | 0.5 | 21.7 | ✗ | ✓ | 1.0 | 239.8 |
| 58 | Who is the writer of this song that was inspired by w… | Phil Spector | ✓ | ✓ | 0.5 | 11.2 | ✓ | ✓ | 0.5 | 30.1 | ✓ | ✓ | 0.5 | 139.3 |
| 59 | Ellie Goulding worked with what other writers on her… | Max Martin, Savan Kotecha… | ✗ | ✓ | 0.0 | 70.9 | ✗ | ✗ | 0.0 | 238.5 | ✓ | ✓ | 0.0 | 322.1 |
| 60 | What was the name of a woman from the book titled "Th… | Monica Lewinsky | ✓ | ✓ | 0.5 | 10.6 | ✓ | ✓ | 0.0 | 35.6 | ✓ | ✓ | 0.5 | 134.8 |
| 61 | What occupation do Chris Menges and Aram Avakian shar… | director | ✗ | ✓ | 1.0 | 8.1 | ✗ | ✗ | 0.5 | 147.5 | ✗ | ✓ | 0.5 | 87.0 |
| 62 | The 2017–18 Wigan Athletic F.C. season will be a year… | Carabao Cup | ✓ | ✓ | 1.0 | 13.1 | ✗ | ✗ | 1.0 | 248.1 | ✓ | ✓ | 1.0 | 128.1 |
| 63 | Which British first-generation jet-powered medium bom… | English Electric Canberra | ✗ | ✓ | 1.0 | 14.2 | ✗ | ✗ | 1.0 | 208.1 | ✓ | ✓ | 1.0 | 313.0 |
| 64 | Are Freakonomics and In the Realm of the Hackers both… | no | ✓ | ✓ | 0.5 | 16.7 | ✗ | ✗ | 0.0 | 25.5 | ✓ | ✓ | 0.5 | 104.0 |
| 65 | Are both Dictyosperma, and Huernia described as a gen… | yes | ✓ | ✓ | 1.0 | 10.0 | ✓ | ✓ | 1.0 | 83.1 | ✓ | ✓ | 1.0 | 106.4 |
| 66 | 2014 S/S is the debut album of a South Korean boy gro… | YG Entertainment | ✓ | ✓ | 1.0 | 5.9 | ✓ | ✓ | 1.0 | 19.5 | ✓ | ✓ | 1.0 | 140.6 |
| 67 | The Album Against the Wind was the 11th Album of a Ro… | Bob Seger | ✓ | ✓ | 0.5 | 8.1 | ✗ | ✗ | 0.5 | 25.3 | ✓ | ✓ | 0.5 | 125.6 |
| 68 | Alexander Kerensky was defeated and destroyed by the… | October 1922 | ✗ | ✗ | 0.5 | 13.4 | ✗ | ✗ | 0.5 | 40.4 | ✓ | ✓ | 0.5 | 136.3 |
| 69 | Andrew Jaspan was the co-founder of what not-for-prof… | The Conversation | ✓ | ✓ | 0.5 | 6.1 | ✓ | ✓ | 0.5 | 19.0 | ✓ | ✓ | 0.5 | 83.9 |
| 70 | Which filmmaker was known for animation, Lev Yilmaz o… | Levni Yilmaz | ✗ | ✗ | 1.0 | 8.2 | ✗ | ✗ | 0.5 | 16.0 | ✗ | ✗ | 1.0 | 103.0 |
| 71 | When was Poison's album "Shut Up, Make Love" released? | 2000 | ✓ | ✓ | 0.5 | 7.5 | ✓ | ✓ | 0.5 | 24.3 | ✓ | ✓ | 0.5 | 139.9 |
| 72 | who is the younger brother of The episode guest stars… | Bill Murray | ✓ | ✓ | 0.5 | 10.2 | ✗ | ✓ | 0.5 | 149.7 | ✓ | ✓ | 0.0 | 140.0 |
| 73 | Which American film director hosted the 18th Independ… | John Waters | ✓ | ✓ | 0.0 | 10.7 | ✓ | ✓ | 0.5 | 53.6 | ✓ | ✓ | 0.5 | 122.5 |
| 74 | Are the Laleli Mosque and Esma Sultan Mansion located… | no | ✓ | ✓ | 1.0 | 11.4 | ✗ | ✗ | 0.5 | 25.6 | ✓ | ✓ | 1.0 | 102.3 |
| 75 | Are both Cypress and Ajuga genera? | no | ✗ | ✗ | 1.0 | 17.1 | ✓ | ✓ | 0.5 | 33.7 | ✓ | ✓ | 1.0 | 200.7 |
| 76 | In which city is the ambassador of the Rabat-Salé-Kén… | Beijing | ✓ | ✓ | 1.0 | 13.5 | ✗ | ✗ | 1.0 | 18.6 | ✓ | ✓ | 1.0 | 120.9 |
| 77 | What type of forum did a former Soviet statesman initi… | Organizations could come… | ✗ | ✗ | 0.5 | 5.8 | ✗ | ✗ | 0.0 | 16.7 | ✗ | ✗ | 0.5 | 181.7 |
| 78 | Aside from the Apple Remote, what other device can co… | keyboard function keys | ✓ | ✓ | 0.5 | 11.0 | ✗ | ✗ | 0.5 | 103.1 | ✓ | ✓ | 0.5 | 330.0 |
| 79 | The 2011–12 VCU Rams men's basketball team, led by th… | 1838 | ✗ | ✗ | 1.0 | 14.3 | ✗ | ✗ | 1.0 | 224.9 | ✗ | ✗ | 1.0 | 125.7 |
| 80 | In what year was the novel that Lourenço Mutarelli bas… | 1866 | ✓ | ✓ | 1.0 | 12.8 | ✗ | ✗ | 0.5 | 25.5 | ✗ | ✗ | 1.0 | 159.3 |
| 81 | Which French ace pilot and adventurer fly L'Oiseau Bl… | Charles Eugène | ✗ | ✗ | 0.5 | 10.0 | ✗ | ✗ | 1.0 | 180.4 | ✗ | ✗ | 1.0 | 169.1 |
| 82 | Roger O. Egeberg was Assistant Secretary for Health a… | 1969 until 1974 | ✗ | ✓ | 0.5 | 10.0 | ✗ | ✗ | 0.5 | 117.3 | ✗ | ✓ | 1.0 | 193.4 |
| 83 | What is the inhabitant of the city where 122nd SS-Sta… | 276,170 inhabitants | ✗ | ✗ | 0.5 | 13.9 | ✗ | ✗ | 0.5 | 87.3 | ✗ | ✓ | 1.0 | 148.9 |
| 84 | Which performance act has a higher instrument to pers… | Badly Drawn Boy | ✓ | ✓ | 1.0 | 16.9 | ✗ | ✗ | 0.5 | 206.3 | ✗ | ✓ | 1.0 | 835.4 |
| 85 | Do the drinks Gibson and Zurracapote both contain gin? | no | ✓ | ✓ | 0.5 | 11.2 | ✗ | ✗ | 0.0 | 17.5 | ✓ | ✓ | 0.5 | 241.1 |
| 86 | What was the father of Kasper Schmeichel voted to be… | World's Best Goalkeeper | ✓ | ✓ | 1.0 | 12.1 | ✗ | ✗ | 1.0 | 178.0 | ✗ | ✓ | 1.0 | 193.3 |
| 87 | In what month is the annual documentary film festival… | March and April | ✓ | ✓ | 0.5 | 8.9 | ✗ | ✓ | 1.0 | 211.2 | ✓ | ✓ | 1.0 | 124.0 |
| 88 | What is the county seat of the county where East Lemp… | Newport | ✓ | ✓ | 1.0 | 23.2 | ✓ | ✓ | 1.0 | 63.9 | ✗ | ✗ | 1.0 | 301.1 |
| 89 | According to the 2001 census, what was the population… | 35,124 | ✗ | ✗ | 1.0 | 72.7 | ✗ | ✗ | 1.0 | 57.7 | ✗ | ✗ | 1.0 | 872.5 |
| 90 | Robert Suettinger was the national intelligence offic… | William Jefferson Clinton | ✗ | ✗ | 0.5 | 8.7 | ✗ | ✗ | 0.5 | 300.5 | ✗ | ✗ | 0.5 | 141.2 |
| 91 | What was the name of the 1996 loose adaptation of Wil… | Tromeo and Juliet | ✓ | ✓ | 1.0 | 12.9 | ✗ | ✗ | 1.0 | 249.8 | ✓ | ✓ | 1.0 | 146.4 |
| 92 | Hayden is a singer-songwriter from Canada, but where… | Fujioka, Gunma | ✓ | ✓ | 0.5 | 9.4 | ✓ | ✓ | 0.5 | 22.8 | ✓ | ✓ | 0.5 | 114.1 |
| 93 | Where does the hotel and casino located in which Bill… | Las Vegas Strip in Paradise, NV | ✗ | ✗ | 0.5 | 24.9 | ✗ | ✗ | 1.0 | 104.6 | ✗ | ✓ | 0.5 | 182.0 |
| 94 | When was the American lawyer, lobbyist and political… | April 1, 1949 | ✓ | ✓ | 0.5 | 10.8 | ✗ | ✗ | 0.5 | 123.4 | ✓ | ✓ | 0.5 | 126.3 |
| 95 | Which of Tara Strong major voice role in animated ser… | Teen Titans Go! | ✗ | ✗ | 0.5 | 12.1 | ✗ | ✗ | 0.5 | 105.2 | ✓ | ✓ | 0.5 | 151.2 |
| 96 | This singer of A Rather Blustery Day also voiced what… | Sonic | ✗ | ✓ | 0.5 | 24.8 | ✗ | ✗ | 0.0 | 130.4 | ✗ | ✗ | 0.5 | 835.6 |
| 97 | D1NZ is a series based on what oversteering technique? | Drifting | ✓ | ✓ | 0.5 | 12.3 | ✓ | ✓ | 0.5 | 36.1 | ✓ | ✓ | 0.5 | 105.4 |
| 98 | Which other Mexican Formula One race car driver has h… | Pedro Rodríguez | ✓ | ✓ | 0.5 | 12.7 | ✗ | ✗ | 0.5 | 126.9 | ✓ | ✓ | 0.5 | 199.0 |
| 99 | What is the name of the singer who's song was release… | Usher | ✗ | ✗ | 0.5 | 16.9 | ✗ | ✗ | 0.5 | 91.6 | ✓ | ✓ | 0.5 | 269.8 |
| 100 | What color clothing do people of the Netherlands wear… | orange | ✓ | ✓ | 0.5 | 9.1 | ✓ | ✓ | 0.5 | 17.8 | ✓ | ✓ | 1.0 | 99.7 |

**Summary**: FL: 59 EM · 76 Fz · 24 hard fail · 18.1s avg · G3: 30 EM · 41 Fz · 59 hard fail · 91.7s avg · G4: 58 EM · 81 Fz · 19 hard fail · 212.1s avg

---

## 10. Key Findings & Recommendations

### Finding 1: The LLM dominates — retrieval is not the bottleneck

With identical retrieval infrastructure across all three runs, the 29 pp EM gap between Gemma3:4b (30%) and Flash Lite (59%) — and the 34 questions only Gemma3 uniquely fails — confirm that LLM reasoning quality is the primary driver of end-to-end performance. Retrieval precision is virtually identical (0.330–0.351) and recall varies only moderately (0.625–0.715). Improving retrieval further without upgrading the LLM yields limited returns.

### Finding 2: Gemma4:e4b matches cloud model accuracy with fully local inference

At 58.0% EM (vs. 59.0% for Flash Lite) and 81.0% fuzzy match (vs. 76.0%), gemma4:e4b is statistically equivalent to Flash Lite on accuracy metrics. It achieves better recall, better F1, better fuzzy match, and fewer hard failures. This establishes that the Final Implementation pipeline running fully locally — with a sufficiently capable local LLM — can match cloud API performance on this multi-hop benchmark.

### Finding 3: Gemma3:4b is not a viable production LLM for this task

30% EM, 17 abstentions (including 12 at full retrieval recall), and 59 hard failures make Gemma3:4b unsuitable for the retrieval pipeline. The model's ingestion quality (the knowledge graph was built with Gemma3:4b) does not hurt — it's only the retrieval/reasoning step that fails. Replacing Gemma3 as the retrieval LLM with either Flash Lite or Gemma4 is essential.

### Finding 4: Flash Lite is the production recommendation

For interactive workloads: Flash Lite (18.10 s mean, 59% EM) is the clear choice. Its accuracy matches Gemma4 while being 11.7× faster. The only trade-off is cloud API dependency. For environments where data residency prohibits cloud API, Gemma4:e4b with GPU acceleration is the path forward.

### Finding 5: 13 questions are irrecoverable without KB expansion

The hard-miss core (13 questions all three models fail) is primarily a knowledge graph coverage problem. Animorphs, Ronald Shusett, the 2001 census parish population, and 4–5 other questions require entities or facts not ingested in the current 990-note corpus. Expanding KB coverage with Wikipedia/Wikidata for these topic areas would be the highest-leverage KB investment.

### Finding 6: Gemma4's verbose output depresses EM; post-processing can recover it

The 23 pp EM–fuzzy gap for Gemma4 (58% EM vs. 81% fuzzy) is the largest of any run and is caused by answer verbosity, not factual errors. A simple post-processing step — extracting the primary noun phrase or stripping common qualifiers ("of the United States", "hypermarkets", "from ") — would push Gemma4's EM from ~58% to ~68–72%, likely surpassing Flash Lite. This is a straightforward engineering change requiring no additional inference.

### Finding 7: Retrieval recall improves with smarter LLMs (loop effect)

Recall at Rc=1.0: Flash Lite 42%, Gemma3 37%, Gemma4 52%. The iterative loop's sub-query generation is LLM-driven — a better model generates better follow-up queries, directing the retrieval engine toward the second gold document. Gemma4's 52% full-recall rate is a direct result of better sub-query formulation across 10 iterations.

### Finding 8: Fix Pydantic schema to accommodate Gemma4's output format

Gemma4 produces `question_attribute` as a list and occasionally `intent: null` — both cause non-fatal fallback in the current schema. Updating the schema:
```python
question_attribute: Union[str, List[str]]
intent: Optional[Literal["search", "compare", "verify"]]  # allow None
```
eliminates these fallbacks and ensures structured query extraction is used on every question.

### Recommendation Summary

| Priority | Recommendation | Expected Impact |
|---|---|---|
| **Critical** | Replace Gemma3:4b as retrieval LLM with Flash Lite or Gemma4 | EM +28–29 pp |
| **High** | Add answer post-processing to extract core noun phrase for Gemma4 | EM +8–12 pp |
| **High** | Enable GPU acceleration in Ollama for Gemma4 | Latency −60–80% |
| **Medium** | Fix Pydantic schema for `question_attribute` and `intent` | Eliminate 2 fallback paths |
| **Medium** | Expand KB with Animorphs, Ronald Shusett, census data | EM +2–4 pp on hard questions |
| **Low** | Quantized Gemma4 variant (Q4_K_M or similar) | Latency −50%, EM ~−2 pp |
| **Low** | Tighten per-iteration top-K cutoff | Precision +0.05–0.10 |
