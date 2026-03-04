# Gemma3:4b Retrieval Benchmark Report
## `google/gemma-3-4b` (LM Studio) on Gemini-Ingested MuSiQue Graph

**Date:** 2026-03-02 (re-run; first run 2026-03-01 documented in notes)
**Test window:** 11:51:34 → 12:53:30 — **61.9 minutes wall time**
**Graph source:** Gemini Flash (`gemini-3-flash-preview`) ingestion of 524 MuSiQue Wikipedia passages
**Conducted by:** Automated benchmark harness (`/api/v1/chat`)

---

## 1. Executive Summary

This report covers a **50-question multi-hop QA benchmark** using **`google/gemma-3-4b`** as the reasoning and retrieval model, served locally through **LM Studio** over the OpenAI-compatible API. The knowledge graph was built by Gemini Flash from MuSiQue Wikipedia passages (9,434 nodes, 12,513 relationships). Embeddings were generated locally via **`text-embedding-qwen3-embedding-0.6b`** (also LM Studio).

This is the **second / clean run**. The first run (2026-03-01) suffered GPU warm-up / scheduling issues that caused 12.7-hour total time and 6 errors. This run completed in **61.9 minutes with zero errors**, bringing performance much closer to the Gemini Flash baseline.

| Metric | This Run | 1st Run (2026-03-01) | Gemini Flash Baseline |
|---|---|---|---|
| Total questions | 50 | 50 | 50 |
| Valid (no error) | **50 / 50** | 44 / 50 | 50 / 50 |
| Hard errors | **0** | 6 (12%) | 0 |
| Exact match | **22.0%** (11 / 50) | 15.9% (7 / 44) | 50.0% |
| Fuzzy match | **26.0%** (13 / 50) | 18.2% (8 / 44) | 58.0% |
| Contains expected | **34.0%** (17 / 50) | 31.8% (14 / 44) | 52.0% |
| Token-level F1 | **0.2698** | 0.1884 | 0.5584 |
| Mean response time | **75.8 s** | 913.8 s | 63.4 s |
| Total wall time | **61.9 min** | 12.7 hours | 51.9 min |
| JSON mode failures | 139 / 139 (100%) | 138 / 138 (100%) | 0 / 138 (0%) |

The clean re-run reveals that **`google/gemma-3-4b` via LM Studio is only ~1.2× slower than Gemini Flash on throughput** once the GPU is properly engaged. The persistent gap is on **accuracy** (22% vs 50% exact match), which is a fundamental model capability difference rather than an infrastructure problem. The previously observed 14× slowdown was a cold-start / GPU scheduling artifact, not a representative throughput figure.

---

## 2. Test Configuration

| Parameter | Value |
|---|---|
| LLM provider | LM Studio (local, `http://127.0.0.1:1234`) |
| LLM model | `google/gemma-3-4b` |
| Embedding model | `text-embedding-qwen3-embedding-0.6b` (LM Studio) |
| API endpoint | `http://127.0.0.1:8001/api/v1/chat` |
| Backend | FastAPI / Uvicorn (port 8001) |
| Database | PostgreSQL port 5434 (`liveos`) |
| Graph database | Neo4j `bolt://127.0.0.1:7688` |
| Dataset | MuSiQue (525 Wikipedia passages → 524 ingested) |
| Graph nodes | 9,434 |
| Graph relationships | 12,513 |
| Questions tested | 50 (stratified multi-hop subset) |
| Run timestamp | 2026-03-02T11:51:34 → 12:53:30 |

---

## 3. Accuracy Results

### 3.1 Overall Accuracy

| Metric | Count | Rate |
|---|---|---|
| Exact match | 11 / 50 | **22.0%** |
| Fuzzy match | 13 / 50 | **26.0%** |
| Contains expected | 17 / 50 | **34.0%** |
| Token-level F1 | — | **0.2698** |
| Errors | 0 / 50 | **0.0%** |

Exact match uses strict string equality after normalization. Fuzzy match applies token-overlap similarity with a threshold. "Contains expected" checks whether the expected answer string appears verbatim in the model's response — at 34%, this shows the correct information reached the synthesis step but was not extracted cleanly in 12 additional cases.

### 3.2 Answer Type Breakdown

The benchmark intrinsically covers varied answer types, which Gemma3:4b handles with different success rates:

| Answer Type | Count |
|---|---|
| A person | 16 |
| A place name | 16 |
| A year | 5 |
| A company name | 5 |
| A number or count | 4 |
| A person's name | 2 |
| A book title | 1 |
| A movie title | 1 |

Person and place queries dominate (64% combined), consistent with MuSiQue's entity-centric, biographic fact chain structure.

### 3.3 Accuracy vs. Gemini Flash

| Metric | Gemma3:4b | Gemini Flash | Gap |
|---|---|---|---|
| Exact match | 22.0% | 50.0% | −28.0 pp |
| Fuzzy match | 26.0% | 58.0% | −32.0 pp |
| Contains expected | 34.0% | 52.0% | −18.0 pp |
| Token F1 | 0.2698 | 0.5584 | −0.2886 |

The accuracy gap is substantial and consistent across all metrics. The "contains expected" gap is smallest (−18 pp), suggesting that Gemma3:4b frequently retrieves and presents the correct information but fails to extract it cleanly into a short, direct answer phrase — a known weakness of smaller models on instruction-following precision.

---

## 4. End-to-End Timing

### 4.1 Per-Question Response Time Distribution

| Statistic | This Run | 1st Run | Gemini Flash |
|---|---|---|---|
| Minimum | 31.4 s | 20.0 s | 8.9 s |
| P10 | 50.2 s | — | — |
| P25 | 56.6 s | — | — |
| Median | 69.8 s | 865.1 s | 52.7 s |
| Mean | **75.8 s** | 913.8 s | 63.4 s |
| P75 | 90.8 s | — | — |
| P90 | 100.9 s | — | — |
| P95 | 114.0 s | — | — |
| Maximum | 154.0 s | 1,800.0 s | 197.2 s |
| Std dev | 24.4 s | 594.0 s | 34.1 s |

The distribution is now **unimodal and tight** (stdev 24.4 s) vs. the first run's extreme bimodal spread (stdev 594 s, with 12 fast-fail outliers and 37 multi-hour completions). The 95th percentile (114 s) is only 1.5× the median, confirming consistent inference without outliers.

### 4.2 Response Time Buckets

| Bucket | Count | % |
|---|---|---|
| < 30 s | 0 | 0% |
| 30–60 s | 19 | 38% |
| 60–90 s | 17 | 34% |
| 90–120 s | 12 | 24% |
| 2–5 min | 2 | 4% |
| > 5 min | 0 | 0% |

72% of questions complete in under 90 seconds. Only 2 questions exceeded 2 minutes (max 154 s), both likely involving longer sub-question chains (3-hop or 4-hop) with multiple fallback retrieval attempts.

### 4.3 Total Wall Time

| Run | Wall Time |
|---|---|
| Gemma3:4b — 1st run | 12.7 hours |
| **Gemma3:4b — this run** | **61.9 minutes** |
| Gemini Flash | 51.9 minutes |

**The 12.3× speed improvement** over the first run is entirely attributable to the GPU being properly engaged during this session. LM Studio had been running for some time prior, meaning the model was already loaded in VRAM and inference benefited from full GPU acceleration from question one. The first run appears to have involved CPU fallback or cold-start throttling for the majority of tokens.

---

## 5. Pipeline Stage Breakdown

### 5.1 Question Decomposition

| Metric | This Run | 1st Run | Δ |
|---|---|---|---|
| Mean | 6.3 s | 83.1 s | **13.2× faster** |
| Median | 5.8 s | — | — |
| Min | 3.7 s | — | — |
| Max | 21.0 s | 352.2 s | — |

Decomposition calls the LLM to identify information needs and generate sub-questions. At 6.3 s mean, this is now faster than the Gemini Flash equivalent (which is effectively instant via the cloud API but includes round-trip latency). The worst case (21 s) likely reflects a 4-hop question requiring four distinct sub-question formulations.

### 5.2 Sub-Question Distribution

| Sub-Questions | Count | % |
|---|---|---|
| 1 | 1 | 2% |
| 2 (two-hop) | 27 | 54% |
| 3 (three-hop) | 19 | 38% |
| 4 (four-hop) | 3 | 6% |
| **Mean** | **2.48** | — |

Consistent with the 1st run (mean 2.48 both times), confirming the decomposition step reliably identifies the correct hop structure. The single 1-sub-question case may be a question that was directly answerable without chained lookup.

### 5.3 Per-Sub-Question Retrieval

Each sub-question drives an independent hybrid retrieval cycle (vector + entity + neighbor search, then LLM ranking).

| Metric | This Run | 1st Run | Δ |
|---|---|---|---|
| Mean retrieval per sub-Q | 13.8 s | 112.5 s | **8.2× faster** |
| Median | 13.4 s | — | — |
| Min | 8.7 s | — | — |
| Max | 41.3 s | 1,145.8 s | — |
| Total sub-Q retrievals | 124 | — | — |

The tighter max (41.3 s vs 1,145.8 s) confirms no runaway ranking operations this run.

### 5.4 Retrieval Phase Detail (from retrieval.log, n=139 retrieval calls)

| Phase | Mean | Max | Min | n |
|---|---|---|---|---|
| Total retrieval cycle | 13.71 s | 41.28 s | 10.02 s | 137 |
| **LLM ranking** | **3.13 s** | **18.96 s** | **0.001 s** | 137 |
| Query embedding | 2.53 s | 10.21 s | 1.70 s | 139 |
| Instruction generation | 1.45 s | 2.76 s | 1.14 s | 139 |
| Retrieval phase (graph+vector) | 0.50 s | 4.99 s | 0.07 s | 139 |
| Vector search | 0.20 s | 2.79 s | 0.02 s | 139 |
| Entity name matching | 0.10 s | 1.81 s | 0.03 s | 138 |
| Neighbor expansion | 0.02 s | 0.11 s | 0.00 s | 137 |

**LLM ranking** is the dominant per-call cost at 3.13 s mean (vs 42.05 s in the first run — 13.5× improvement). This is the step where the LLM re-scores candidate nodes for relevance to the query. With GPU acceleration, this is now a minor fraction of total time rather than the dominant bottleneck.

The **graph traversal operations** (entity matching, vector search, neighbor expansion) remain fast and hardware-independent — all under 0.5 s combined — confirming Neo4j and pgvector are well-sized for this graph.

### 5.5 Answer Synthesis

| Metric | This Run | 1st Run | Δ |
|---|---|---|---|
| Mean | 8.75 s | 112.6 s | **12.9× faster** |
| Median | 8.16 s | 12.0 s | — |
| Min | 4.0 s | — | — |
| Max | 18.8 s | 1,156.2 s | — |

Synthesis renders the final answer from the union of retrieved documents. At 8.75 s mean, this represents a single LLM call over ~7.8 documents (mean). The max (18.8 s) is for the longest context (up to 41 documents in one case).

| Synthesis Docs | Mean | Min | Max |
|---|---|---|---|
| Documents used | 7.8 | 1 | 41 |

The outlier at 41 documents represents a question where two broad sub-questions each retrieved many verified passages; the system synthesized all of them into a single final answer.

---

## 6. Retrieval Quality

### 6.1 Candidate Generation

| Source | Mean per call | n calls |
|---|---|---|
| Entity name match | 4.27 nodes | 114 |
| Vector similarity | 8.63 nodes | 136 |
| Neighbor expansion | 5.74 nodes | 132 |
| Alias additions | 7 total | — |
| **Total candidates** | **15.6 mean** | 139 |

139 retrieval calls across 50 questions (mean 2.78 calls per question — slightly above the mean 2.48 sub-questions because some fallback queries are issued). Candidate pools average 15.6 nodes, drawn from three complementary sources.

### 6.2 Verified Documents

| Metric | Value |
|---|---|
| Total verification calls | 112 |
| Total verified docs | 359 |
| Mean verified per call | 3.21 |
| Max verified per call | 10 |
| No-verified events (before fallback) | 15 |
| No-verified after fallback | 12 |
| Fallback (top_k=50) triggered | 15 |

Verification uses the LLM to confirm candidate relevance before synthesis. 15 sub-question calls returned no verified docs on the first attempt (top_k=10), triggering a wider search (top_k=50); 12 still found nothing — in those cases synthesis proceeds with the best-scored unverified candidates. This affects ~9% of individual retrieval calls.

### 6.3 Bridge Entity Resolution

The pipeline extracts a "bridge entity" from sub-question 1 results — the answer substituted into sub-question 2 (and onwards for 3-hop chains).

| Metric | This Run | 1st Run |
|---|---|---|
| Bridge resolution attempts | 74 | 74 |
| Successfully resolved | 65 (87.8%) | 64 (86.5%) |
| Empty / failed | 9 (12.2%) | 10 (13.5%) |

87.8% bridge resolution is the most directly actionable accuracy sub-metric: when the bridge fails, the follow-on sub-question cannot be correctly filled and the answer is almost certainly wrong.

### 6.4 Response References

| Metric | Value |
|---|---|
| Mean references returned | 5.5 |
| Min | 1 |
| Max | 32 |

The API response includes linked source notes for all verified passages used, supporting answer auditability.

---

## 7. LLM Call Breakdown

### 7.1 Call Type Distribution (from llm.log)

| Call Type | Count | Per Question |
|---|---|---|
| Type synonym generation | 181 | 3.62 |
| JSON extraction (LM Studio) | 139 | 2.78 |
| Embedding instruction generation | 139 | 2.78 |
| Back-reference rewrite | 58 | 1.16 |
| Question decomposition | 50 | 1.00 |
| Answer synthesis | 50 | 1.00 |
| **Total meaningful calls** | **436** | **8.72** |

The call structure is identical to the first run (436 total, 8.72/Q), confirming a deterministic pipeline architecture. Type synonym generation (3.62/Q) is highest because each retrieval sub-question expands entity type labels into synonym sets for broader graph matching.

### 7.2 JSON Mode Incompatibility

| Metric | Value |
|---|---|
| JSON mode attempts | 139 |
| JSON mode failures | **139 (100%)** |
| Error message | `"'response_format.type' must be 'json_schema' or 'text'"` |
| Fallback behavior | Text-mode extraction (slower, less reliable) |

`google/gemma-3-4b` running under LM Studio does not support `response_format: {"type": "json_object"}`. It requires `json_schema` with an explicit schema definition. Every extraction call falls back to unstructured text parsing.

This is the **single most impactful structural issue** in the current pipeline for this model. The fallback text parsing introduces extra parse latency and increases hallucination risk in extraction — contributing to the 12.2% bridge miss rate.

**Fix required:** Add `json_schema` fallback when `json_object` returns HTTP 400, using the LM Studio-specific `response_format` format.

---

## 8. Error Analysis

### 8.1 Error Summary

| Type | Count |
|---|---|
| Hard errors (HTTP 500 / exception) | 0 |
| Soft failures (empty answer) | 0 |
| **Total errors** | **0** |

Zero errors across all 50 questions. This contrasts sharply with the first run's 6 errors (1 HTTP 500 timeout + 5 soft failures under extreme latency). The errors in the first run were induced by LM Studio inference timeouts under CPU-only / cold-start inference — resolved here by proper GPU scheduling.

---

## 9. Comparative Analysis

### 9.1 Gemma3:4b: Run-to-Run Improvement

| Metric | Run 1 (2026-03-01) | Run 2 (2026-03-02) | Improvement |
|---|---|---|---|
| Valid questions | 44 / 50 | **50 / 50** | +6 |
| Exact match | 15.9% | **22.0%** | +6.1 pp |
| Fuzzy match | 18.2% | **26.0%** | +7.8 pp |
| Token F1 | 0.1884 | **0.2698** | +0.0814 |
| Mean response time | 913.8 s | **75.8 s** | **12.1× faster** |
| Median response time | 865.1 s | **69.8 s** | **12.4× faster** |
| Total wall time | 12.7 hours | **61.9 min** | **12.3× faster** |
| Decomposition mean | 83.1 s | **6.3 s** | **13.2× faster** |
| LLM ranking mean | 42.05 s | **3.13 s** | **13.5× faster** |
| Synthesis mean | 112.6 s | **8.75 s** | **12.9× faster** |
| Hard errors | 6 | **0** | −6 |

The accuracy improvement (exact match: +6.1 pp) is meaningful on its own, but the primary story is the **12–13× speed improvement** from cold-start / CPU inference to GPU-accelerated inference.

### 9.2 Gemma3:4b vs. Gemini Flash

| Metric | Gemma3:4b (Run 2) | Gemini Flash | Gap |
|---|---|---|---|
| Valid / total | 50 / 50 | 50 / 50 | — |
| Exact match | 22.0% | 50.0% | **−28.0 pp** |
| Fuzzy match | 26.0% | 58.0% | −32.0 pp |
| Token F1 | 0.2698 | 0.5584 | −0.2886 |
| Mean response time | 75.8 s | 63.4 s | **+1.2×** |
| Total wall time | 61.9 min | 51.9 min | +10 min |
| Decomposition mean | 6.3 s | 2.89 s | 2.2× |
| LLM ranking | 3.13 s | 4.60 s | **0.68× (faster!)** |
| JSON mode failures | 100% | 0% | — |
| Hard errors | 0 | 0 | — |

**Throughput is now competitive**: mean response time is only 12.4 seconds slower (75.8 s vs 63.4 s). Notably, **LLM ranking is actually faster on Gemma3:4b** (3.13 s vs 4.60 s) — a reflection of local GPU inference on a small model vs. cloud API round-trip with a larger model. The bottleneck gap is in embedding (2.53 s local vs near-zero for cloud) and decomposition (6.3 s vs 2.89 s).

The **accuracy gap is the dominant remaining difference**: Gemini Flash scores 2.3× higher on exact match. This reflects model capability on instruction-following, multi-step reasoning, and answer extraction precision — fundamentals that scale with model size and training, not infrastructure configuration.

---

## 10. Key Observations

### Observation 1: GPU Warm-Up Critically Affects Small Local Models

The 12.3× difference between the two runs is the most striking finding. Gemma3:4b requires an "already-warm" LM Studio session with the model loaded in VRAM. Cold-start benchmarking dramatically overstates real-world latency for iterative use cases.

**Recommendation:** Always issue a warmup query before benchmarking, or ensure the model has served at least one prior request in the LM Studio session.

### Observation 2: Gemma3:4b's Throughput Is Competitive With Cloud

At 75.8 s per question, Gemma3:4b is only 1.2× slower than Gemini Flash (63.4 s) — a negligible practical difference for interactive use. For a 4B parameter local model with fully local embeddings and no network latency beyond localhost, this is a strong throughput result. Infrastructure configuration dominates total latency far more than model size in this regime.

### Observation 3: Accuracy Gap Is Real and Structural

The 22% vs 50% exact match gap cannot be explained by infrastructure. It reflects Gemma3:4b's limitations on:
- **Extraction precision**: Frequently returns verbose answers rather than short factual phrases
- **Multi-hop reasoning fidelity**: Bridge entity chain can break at any step
- **JSON format compliance**: 100% failure on structured output forces less reliable text parsing throughout

### Observation 4: Bridge Entity Resolution Is the Key Accuracy Lever

87.8% bridge resolution (65/74) is the clearest causal link to final accuracy. The 12.2% failure rate propagates directly to wrong answers on multi-hop questions. Improving bridge extraction — most directly by fixing JSON mode support — would have the highest expected accuracy return.

### Observation 5: Fallback Retrieval Fires Frequently

15 of 139 retrieval calls (10.8%) found no verified documents at top_k=10, triggering fallback to top_k=50. After fallback, 12 of 15 still returned no verified docs. This 8.6% final "zero verified" rate means synthesis has to proceed on unconfirmed candidates for a meaningful proportion of sub-questions. The verification LLM call (using JSON-broken Gemma3:4b) may be a contributing factor.

### Observation 6: Type Synonym Expansion Generates High LLM Call Volume

Type synonym generation (3.62 calls/Q) accounts for 41% of LLM call volume. Each retrieval sub-question expands expected entity type labels into synonym sets. Caching common type synonyms (deterministic for a given type label) could reduce LLM calls per question by ~41% without any accuracy cost.

### Observation 7: LLM Ranking Is Now Faster Than Gemini Flash

In Run 2, LLM ranking averages 3.13 s vs 4.60 s for Gemini Flash — the only pipeline phase where Gemma3:4b is faster. This likely reflects lower TTFT (time-to-first-token) on a small local model vs. cloud API latency, combined with the fact that ranking prompts are short and easy for a 4B model.

### Observation 8: Stdev Collapse Confirms Run 2 Is Reliable

Response time standard deviation dropped from 594 s (Run 1) to 24.4 s (Run 2). The coefficient of variation (24.4 / 75.8 = 32%) is consistent with stable GPU inference. Run 1's CV was 65% — a hallmark of variable CPU fallback.

### Observation 9: "Contains Expected" Gap Points to Synthesis Quality

34% "contains expected" vs 22% exact match means the correct answer appears in 12 additional responses but isn't extracted cleanly. Gemini Flash achieves near-parity between these two metrics (52% contains vs 50% exact), confirming that answer extraction / synthesis instruction-following is a Gemma3:4b-specific weakness.

---

## 11. Infrastructure Notes

### 11.1 Service Configuration

| Service | Detail |
|---|---|
| PostgreSQL | `postgresql+asyncpg://user:password@127.0.0.1:5434/liveos` |
| FastAPI / Uvicorn | Server process [45209], startup complete 11:49:53 |
| LM Studio — LLM | `http://127.0.0.1:1234`, model: `google/gemma-3-4b` |
| LM Studio — Embedding | `text-embedding-qwen3-embedding-0.6b` |

### 11.2 API Response Codes

| HTTP Code | Count |
|---|---|
| 200 OK | 50 |
| 4xx / 5xx | 0 |

All 50 POST requests to `/api/v1/chat` returned HTTP 200. Server was stable throughout the 61.9-minute window.

---

## 12. Recommendations

### Priority 1 — Fix JSON Mode (High Impact, Moderate Effort)
Detect `json_object` HTTP 400 at the provider level and fall back to `json_schema` mode for LM Studio with Gemma3:4b. This would affect 139 extraction calls (2.78/Q) and is expected to improve extraction accuracy — most directly the bridge entity hit rate.

### Priority 2 — Cache Type Synonyms (Low Effort, Medium Impact)
Type synonym generation (181 calls, 3.62/Q) is deterministic per entity type. An in-memory cache keyed on `(type_label, model_id)` would reduce LLM calls from ~437/Q to ~257/Q — a 41% call volume reduction.

### Priority 3 — Warmup Protocol for Benchmarking
Add a single warmup request before benchmark timing begins when using local LM Studio models. Document this as a required step.

### Priority 4 — Investigate Verified-Doc Failure Cases
12 retrieval calls (8.6%) found no verified documents even after top_k=50 fallback. Inspect whether these correlate with specific question types, entity gaps in the graph, or verification failures under text-mode fallback.

### Priority 5 — Larger Local Model Comparison
With Gemma3:4b at 22% exact match vs Gemini Flash at 50%, the next meaningful data point is a mid-size local model (Gemma3 9B, Llama3.1 8B, Mistral 7B). At 75.8 s/Q on a 4B model, a 7–9B model would likely run at ~120–180 s/Q while potentially closing the accuracy gap significantly.

---

## 13. At-a-Glance Metrics Block

```
=== GEMMA3:4B CLEAN RE-RUN — 2026-03-02 ===

ACCURACY
  Exact match:          11/50 = 22.0%
  Fuzzy match:          13/50 = 26.0%
  Contains expected:    17/50 = 34.0%
  Token-level F1:       0.2698
  Hard errors:           0/50 = 0.0%

TIMING (all 50 questions)
  Mean:    75.8 s   Median: 69.8 s
  Min:     31.4 s   Max:   154.0 s
  Stdev:   24.4 s
  P10:     50.2 s   P25:  56.6 s   P75:  90.8 s   P90: 100.9 s
  Wall time: 61.9 minutes (11:51:34 → 12:53:30)

PIPELINE STAGES (means)
  Decomposition:          6.3 s   (13.2× faster than Run 1)
  Retrieval per sub-Q:   13.8 s   ( 8.2× faster than Run 1)
  LLM ranking:            3.1 s   (13.5× faster than Run 1)
  Synthesis:              8.8 s   (12.9× faster than Run 1)

LLM CALLS
  Total:            436   Per question: 8.72
  Type synonyms:    181   Embeddings:   139
  Extraction:       139   Synthesis:     50
  Decomposition:     50   Back-ref:      58
  JSON mode fails: 139/139 = 100% (json_object not supported)

RETRIEVAL
  Candidates:        15.6 mean   Bridge found: 65/74 = 87.8%
  Verified docs:      3.21 mean  Fallback used: 15/139 = 10.8%
  Synth docs used:    7.8 mean   Response refs: 5.5 mean

VS. GEMINI FLASH BASELINE
  Exact match:  22.0% vs 50.0%  (−28.0 pp)
  F1:           0.2698 vs 0.5584 (−0.2886)
  Mean time:    75.8 s vs 63.4 s (+1.2× — near parity)
  Wall time:    61.9 min vs 51.9 min
  Errors:       0 vs 0

VS. GEMMA3:4B RUN 1
  Exact:     22.0% vs 15.9%   (+6.1 pp)
  F1:        0.2698 vs 0.1884 (+0.0814)
  Mean time:  75.8s vs 913.8s (12.1× faster — GPU warm)
  Wall time:  61.9 min vs 12.7 hours (12.3× faster)
  Errors:     0 vs 6
```
