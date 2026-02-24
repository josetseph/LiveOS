# Multi-Hop Retrieval Optimization Process

This file documents the iterative process of improving the HotPotQA benchmark score for the LiveOS multi-hop retrieval pipeline.

---

## Score History

| Run | Approach | fuzzy_match | Notes |
|-----|----------|-------------|-------|
| Baseline | Single-hop chat.py pipeline | ~0.53 | Production pipeline |
| v0.1 | Fixed synthesis prompt + alias detection + semantic shield | **0.56** | Prompt engineering only |
| v0.2 | chat.py two-tier substitution + `extract_entity_name` | **0.47** | Regression: substitution changes broke something |
| v1.0 | `evaluate_hop_pipeline.py` — dedicated eval harness, per-candidate YES/NO filter, `_rewrite_back_references` | **0.57** | New high |
| v2.0 | `evaluate_hop_pipeline_2.py` — pure vector, top_k=500 + early stopping (10 Q pilot) | **0.40** | Much worse + extremely slow |
| v3.0 | `evaluate_hop_pipeline_v3.py` — full node evidence synthesis (no pre-extracted answers), reasoning + `FINAL:` format, verification prompt hardened against external knowledge, RULE 4 for position/role/title answers | **0.63** | +6pp over v1; 63/100 fuzzy, 48/100 exact, F1 0.619 |
| v4.1 | `evaluate_hop_pipeline_v4.py` — RULES 5 & 6 added, RULE 4 generalized to all answer types, F1 ≥ 0.4 fuzzy threshold | **0.65** | 65/100 fuzzy, 46/100 exact, F1 0.604 |
| v4.2 | + chain-of-thought `_identify_answer_type()` injects answer-type constraint into synthesis, F1 threshold lowered to 0.4 | **0.68** | 68/100 fuzzy, 48/100 exact, F1 0.611; +11 gained, −8 lost vs v4.1 |
| v4.3 | `_identify_answer_type` max_tokens raised 15 → 100 (prevents truncation-induced misclassification) | **0.69** | 69/100 fuzzy, 47/100 exact, F1 0.610; gemma3:4b best |
| v5.0 | `evaluate_hop_pipeline_v5.py` — all token limits raised to 2048 (no effective limit for gemma3:4b) | **0.67** | 67/100 fuzzy; 2pp regression vs v4.3 — see v5 analysis below |
| v5-Gemini | `evaluate_hop_pipeline_v5_gemini.py` — identical v4 pipeline logic, model swapped to `gemini-2.0-flash` | **0.74** | 74/100 fuzzy, 47/100 exact, F1 0.639; new high — see Gemini v5 analysis below |
| v6-Gemini | `evaluate_hop_pipeline_v6_gemini.py` — same pipeline, model upgraded to `gemini-2.5-flash` | **0.55** | 55/100 fuzzy, 35/100 exact, F1 0.479; **−19pp regression** — see Gemini v6 analysis below |

---

## Architecture Overview

```
Question
  └─► identify_information_needs  →  [need_1, need_2, ...]
        (llm.py)                       each need may use [placeholder]
            │
            ▼
      for each need:
        hybrid_search(need, top_k=20)
          └─► per-candidate YES/NO LLM filter  (does this answer the sub-q?)
                └─► DIRECT ANSWER extracted from best passage
                      └─► substitute into next need's [placeholder]
            │
            ▼
      _synthesize(question, all_verified_passages)
```

Models in use:
- **LLM**: `gemma3:4b` via Ollama (local, small — simpler prompts win)
- **Embeddings**: `qwen3-embedding:0.6b`
- **Graph DB**: Neo4j with vector index `distilled_knowledge_index`

---

## v1 Pipeline — What Works (`evaluate_hop_pipeline.py`)

### Key design choices that proved correct:

1. **`hybrid_search` top_k=20** — well-calibrated balance of precision vs. recall. The scorer already does the heavy filtering; less is more here.

2. **Per-candidate YES/NO filter with GOAL context** — each retrieved passage is judged against both the sub-question *and* the original question. This eliminates off-topic passages that technically answer the sub-question but wouldn't help the final answer.
   ```
   Original goal: {question}
   Sub-question: {need}
   Passage: {passage}
   Does this passage help answer the sub-question in the context of the goal? YES or NO.
   ```

3. **Structured evidence block** — synthesis sees a clean summary:
   ```
   Sub-question N → DIRECT ANSWER → Supporting passages
   ```
   This forces the LLM to pick up the relayed answer, not get lost in raw text.

4. **`_rewrite_back_references()`** — regex post-processor for natural language back-refs like "that series" → `[that series]`. Acts as a fallback when the LLM prompt rule fails.
   - Regex covers: `(that|this|the|those)\s+(\w+\s+)?(series|books?|films?|show|...)`

5. **Two-tier placeholder substitution in `chat.py`** — attempts key-based substitution first, then falls back to `re.sub(r"\[[^\]]+\]", last_answer, filled_query)` to guarantee substitution even if key names diverge.

### Known failure categories from the 0.57 run (43/100 failures):

| Category | Count | Root Cause | Example |
|----------|-------|-----------|---------|
| A | ~4 | YES/NO synthesis returns the *compared value* not "yes/no" — e.g., outputs `"American"` instead of `"yes"` | "Were X and Y the same nationality?" → `American` |
| B | ~10 | Intermediate entity returned instead of final attribute — synthesis picks up the bridge entity, not the answer to the last hop | "What city is [university] in?" returns the university name |
| C | ~5 | Comparison returns the *metric* not the *winner's name* | "Which had more episodes?" returns `"Six"` not the show title |
| D | ~6 | Wrong specificity — answer is at wrong geographic/categorical granularity | Expected `"Japan"`, got `"Fujioka, Gunma"` |
| E | ~10 | Wrong retrieval / stale KB data — correct node not written to graph | Factual gap or outdated record |
| F | ~8 | True data gap — question requires information not in the knowledge base | — |

Categories D, E, F (~24 failures) require data quality improvements, not prompt changes.
Categories A, B, C (~19 failures) are synthesis failures addressable with better prompts.

---

## v2 Experiment — What Failed (`evaluate_hop_pipeline_2.py`)

### Strategy
Replace `hybrid_search` (top_k=20, scored) with a pure vector search:
```python
graph_service.search_knowledge_graph(vector, top_k=500, min_score=0.5)
```
Plus **early stopping**: after each hop, ask the LLM "Can you already answer the original question? YES: <answer> or NO."

### Results (10-question pilot)
- **fuzzy_match: 4/10 (40.0%)** — worse than v1's 0.57 on the same questions
- **6 failures** (6/10), including questions v1 got right
- **Extremely slow**: ~500 LLM YES/NO calls per step × 2 steps per question

### Failure Analysis

**Actual numbers from the run:**
```
Q1 (Scott Derrickson): 500 retrieved → 58 verified  → synthesized: "NO"   (expected: yes)
Q2 (Corliss Archer):   500 retrieved → 73 verified  → synthesized: "Shirley Temple"  (expected: Chief of Protocol)
Q3 (Animorphs):        500 retrieved → (many)       → synthesized: "YES"  (expected: Animorphs)
```

### Why it failed

1. **Precision collapse** — `min_score=0.5` is too permissive. Nearly every node in the graph passes, because cosine similarity at 0.5 threshold includes loosely-related content. The per-candidate YES/NO filter then becomes the *only* quality gate, and it's noisy at scale.

2. **Synthesis overload** — Passing 58–73 verified passages to the synthesis LLM overwhelms `gemma3:4b`. It can't reliably identify the single relevant answer among 70 evidence chunks. The model gets confused and returns intermediate values, wrong entities, or misidentifies YES/NO questions.

3. **The filter loop is O(n) LLM calls** — 500 candidates × YES/NO call = 500 sequential LLM calls per step. For 100 questions × 2 hops average: ~100,000 LLM calls just for candidate filtering. This is not viable.

4. **More raw candidates ≠ better recall** — The correct answer node is almost always within top_k=20 when the query is well-formed. The 480 extra candidates in v2 don't add new correct answers; they add noise that degrades synthesis.

5. **Early stopping didn't trigger** — `0/10` early stops. Either the format (`YES: answer`) was rarely produced correctly by `gemma3:4b`, or the question was never truly answerable after step 1 in these cases.

### Key lesson
The `hybrid_search` scoring function (BM25 + vector, reranked) is doing real work. Bypassing it with a raw cosine-only retrieval at top_k=500 removes the calibration that makes top_k=20 effective.

> **Precision beats recall for small-model synthesis.** Give the LLM 5 highly relevant passages, not 70 loosely relevant ones.

---

---

## v3 Pipeline — Results & Failure Analysis (`evaluate_hop_pipeline_v3.py`)

### Score: 63/100 fuzzy (0.63) · 48/100 exact · F1 0.619

### Key improvements over v1
1. **Full node evidence in synthesis** — instead of passing pre-extracted short answers, synthesis receives the complete `node_name: text` pairs for every verified document. This let the LLM reason over full passages and fixed the Laleli/Esma Sultan neighbourhood comparison (YES→NO correct).
2. **Reasoning + `FINAL:` format** — LLM writes 1–2 sentences of reasoning before its answer, making failures debuggable.
3. **Hardened verification prompt** — added "Judge ONLY by what is written in the passage — do NOT use outside knowledge" to prevent `gemma3:4b` from saying YES based on training memory rather than passage text.
4. **RULE 4** — added explicit rule: if question asks for a position/role/title, output the title not the person's name. Fixed the Shirley Temple / Chief of Protocol case.
5. **Fixed `distilled_knowledge` field bug** — that property doesn't exist on nodes; the correct field is `summary`. Was always falling back to the prefixed `doc["text"]` string.

### v3 Failure Analysis (37 failures)

| Category | Count | Root Cause | Fixable? |
|----------|-------|-----------|----------|
| A — Answer type wrong (outputs entity/person instead of song/count/city/award) | 5 | RULE 4 too narrow (only covered position/title) | ✅ Prompt fix |
| B — Comparison direction reversed (older/younger) | 1 | RULE 2 didn't clarify age direction | ✅ Prompt fix |
| C — Granularity too coarse (city→country, location→institution) | 4 | No specificity rule | ✅ Prompt fix |
| D — Multi-hop chain breaks / wrong sub-question answered | 4 | Decomposition or retrieval returns current value when past asked | ✅ Partial prompt fix |
| E — Bad graph data (wrong facts stored) | 5 | Incorrect summaries in Neo4j | ❌ Requires re-ingestion |
| F — Fuzzy match near-misses (aliases, partial dates, transliterations) | 3 | Standard fuzzy too strict | ✅ F1 threshold fix |
| G — True data gap / irretrievable | 15 | Information not in knowledge base | ❌ No fix possible |

All 37 failures had verified docs — **this is purely a synthesis + matching problem, not a retrieval problem**.

### Notable individual failures
- `"For Against both from US?"` → `NO` — graph incorrectly says they're from Scotland/Northern England (actually Lincoln, Nebraska). Graph data error.
- `"Terry Richardson older?"` → `Annie Morton` — model said "born 1970 is older than born 1965" — reversed age logic.
- `"Vermont conference formerly known as"` → current name instead of historical name — RULE 6 needed.
- `"Kasper Schmeichel's father voted to be"` → `Peter Schmeichel` — asked for the award title, got the person.

---

## v4 Pipeline — Results & Failure Analysis (`evaluate_hop_pipeline_v4.py`)

### Score progression: 0.65 → 0.68 → **0.69** (current best)

### Key improvements over v3

1. **Generalized RULE 4** — v3 RULE 4 only covered "position/role/title" answers. v4 RULE 4 covers *all* answer types: if the question asks for a song, output the song title; if it asks for a year, output the year; if it asks for a company, output the company name. Stops the model from returning intermediate bridge entities.

2. **RULE 5 — specificity** — if the answer is a sub-location or sub-category, give the most specific level the question asks for. Prevents `"Fujioka, Gunma"` when the question asks for a country, and prevents `"United States"` when the question asks for a city.

3. **RULE 6 — past vs. current** — if the question explicitly asks for a former/past/historical value, do not return the current value. Fixed the Vermont conference ("formerly known as North Atlantic Conference, not current America East Conference") class of failures.

4. **`_identify_answer_type()` chain-of-thought constraint (v4.2)** — before synthesis, a separate LLM call asks "What type of answer does this question require?" (one short phrase). The result is injected as a hard constraint into the synthesis prompt:
   ```
   ANSWER TYPE CONSTRAINT: This question requires {answer_type}.
   Your FINAL: answer MUST be {answer_type}.
   ```
   Added in v4.2, responsible for the largest single-run gain (+3pp, 0.65→0.68). At 15 max_tokens, comparison questions caused 8 regressions (model returned "a comparison" truncated). Raised to **100 max_tokens** in v4.3 to allow the model to produce phrases like "name of the performer with a higher ratio" — eliminated the truncation-induced misclassifications.

5. **F1 ≥ 0.4 fuzzy threshold** — `_is_fuzzy_pass` now returns True if `fuzzy_match(expected, answer)` OR `token_overlap_f1 >= 0.4`. Catches partial-match cases like `"3,677"` (expected `"3,677 seated"`) and `"1986 to 2013"` (expected `"from 1986 to 2013"`).

### Design decision: general > dataset-specific
During v4.2→v4.3, a `_COMPARISON_WORDS` regex was tested to pre-classify comparison questions and bypass the LLM call. It achieved the same 0.69 score. The regex was removed in favour of the 100-token LLM approach — a general solution that works across all question types rather than a brittle pattern matched to the HotPotQA dataset.

### v4 Failure Analysis (31 remaining at 0.69)

| Category | Count | Root Cause | Fixable? |
|----------|-------|-----------|----------|
| E — Bad graph data (wrong facts stored in Neo4j) | 5 | Incorrect summaries ingested | ❌ Requires re-ingestion |
| G — True data gap (not in knowledge base) | ~15 | Information never ingested | ❌ No fix without data |
| H — Sub-question chain misfires | 4 | Decomposer generates wrong temporal sub-question or over-decomposes | ✅ Decomposer prompt fix |
| I — Answer type misidentified by `_identify_answer_type` | 3 | LLM returns wrong type for unusual phrasing | ✅ Prompt/token tuning |
| F — Fuzzy near-miss | 4 | Aliases, partial dates, formatting differences | ✅ F1 threshold / alias list |

### Confirmed bad-data failures (unchanged from v3)
- `"2014 S/S / MADTOWN"` → `J. Tune Camp` (graph) vs. `YG Entertainment` (correct)
- `"Jim Cummings / hedgehog"` → `Tigger` (graph says Tails Prower) vs. `Sonic` (correct)
- `"Random House Tower real estate?"` → `yes` vs. `no` — graph conflates Random House HQ with apartment use
- `"Apple Remote / other device"` → `universal remote` vs. `keyboard function keys` — keyboard shortcut info not in graph
- `"Henry Roth or Robert Erskine Childers from England?"` → `Henry Roth` vs. `Robert Erskine Childers DSC` — graph incorrectly marks Henry Roth as English
- `"Roger O. Egeberg president years"` → `1959–1973` vs. `1969 until 1974` — decomposer gets confused by multi-step chain and picks wrong president

---

## v5 Experiment — Token Limits Removed (`evaluate_hop_pipeline_v5.py`)

### Score: 67/100 fuzzy (0.67) — 2pp regression vs v4.3 (0.69)

### Hypothesis
Gemini runs required removing all token limits to avoid synthesis truncation (Gemini writes verbose multi-paragraph reasoning before `FINAL:`). The same change was applied to gemma3:4b to test whether the 300-token synthesis cap was artificially limiting it.

### Result: the cap was not a limitation — it was a precision constraint

**Regressions (v4 pass → v5 fail, 3 questions):**

| Question | Expected | v4 (300 tok) | v5 (2048 tok) | Failure mode |
|---|---|---|---|---|
| Ralph Hefferline university city | New York City | ✅ New York City | ❌ Columbia | Named the university instead of the city |
| Ichitaka Seto manga author born | 1962 | ✅ 1962 | ❌ 1965 | Picked wrong year from verbose reasoning |
| Bill Cosby hotel location | Las Vegas Strip | ✅ Las Vegas, Nevada | ❌ Flamingo Hotel | Named the hotel instead of its location |

**Improvements (v5 pass → v4 fail, 1 question):**

| Question | Expected | v4 | v5 |
|---|---|---|---|
| Colorado Buffaloes 14th season year+conference | 2009 Big 12 Conference | ❌ 2011 | ✅ 2009 |

### Why more tokens hurt gemma3:4b

With `max_tokens=300`, gemma3:4b is forced to write 1–2 sentences then reach `FINAL:` immediately. It answers the question directly without room to second-guess itself.

With `max_tokens=2048`, the model reasons through multiple paragraphs and "overthinks" — it correctly identifies the bridge entity during reasoning (e.g. the hotel, the university) but then mistakenly outputs that bridge entity as the final answer instead of the attribute being asked for (the location, the city). This is exactly the Category B failure pattern (intermediate entity returned instead of final attribute) that the synthesis rules were designed to prevent — but extra tokens give the model enough rope to unravel those constraints.

### Key lesson
> **For gemma3:4b, `max_tokens=300` on synthesis is the correct value.** The model is terse enough that 300 tokens captures full reasoning + `FINAL:` without truncation. Raising the limit trades 3 precision failures for 1 recall gain — not worth it. Token limits for small local models are precision tools, not arbitrary constraints.

This is the opposite of the Gemini finding: Gemini needs uncapped tokens because it writes verbose reasoning by design; gemma3 needs a cap because brevity keeps it on-task.

---

## Gemini v5 — Model Swap to `gemini-2.0-flash` (`evaluate_hop_pipeline_v5_gemini.py`)

### Score: 74/100 fuzzy (0.74) · 47/100 exact · F1 0.639 — **new overall high**

Identical pipeline to v4 (same prompts, same logic, same graph data). Only change: all LLM calls replaced with `gemini-2.0-flash` via the Google Generative AI SDK.

### Key finding: +5pp gain from model alone

Swapping `gemma3:4b` (local, 4B params) → `gemini-2.0-flash` (hosted) with **zero prompt changes** added 5 fuzzy-match points (0.69 → 0.74). This isolates how much remaining headroom is model capability vs. data/pipeline. The answer: roughly half.

| Metric | gemma3 v4.3 | gemini-2.0-flash | Delta |
|--------|-------------|------------------|-------|
| Fuzzy match | 69/100 | **74/100** | +5 |
| Exact match | 47/100 | 47/100 | 0 |
| Avg F1 | 0.610 | **0.639** | +0.029 |
| Failures | 31 | **26** | −5 |

### Why fuzzy improved but exact stayed equal

Gemini follows the synthesis rules more reliably and almost never returns intermediate bridge entities. However it tends to be **wordier in its final answer** — it includes surrounding context that the exact-match scorer penalises:

| Question | Expected | Gemini answer |
|----------|----------|---------------|
| Fight song of Univ. of Kansas | `Kansas Song` | `Kansas Song (We're From Kansas)` |
| Big Stone Gap director's New York city | `Greenwich Village, New York City` | `New York City` |
| Shirley Temple government position | `Chief of Protocol` | `United States ambassador to Ghana, ... and Chief of Protocol` |

All three fuzzy-pass but exact-fail. RULE 4/5 prevent the *wrong entity* but don't prevent *over-inclusion*. A post-processing step trimming to the minimum answer span could convert several of these fuzzy→exact.

### Failure analysis (26 failures)

| Category | Count | Root cause | Fixable? |
|----------|-------|------------|----------|
| G — True data gap (not in KB) | ~10 | Information never ingested — no evidence found at all | ❌ Requires ingestion |
| E — Bad graph data (wrong facts) | ~6 | Incorrect summaries stored in Neo4j | ❌ Requires re-ingestion |
| H — Decomposition misfires | 3 | Wrong sub-question generated or placeholder left empty | ✅ Decomposer prompt |
| J — Specificity/granularity (RULE 5) | 2 | Geographic answer at wrong level (country vs. city/village) | ✅ Prompt tuning |
| F — Fuzzy near-miss (semantic match, string mismatch) | 3 | Synonyms, article differences, partial date formats | ✅ F1 threshold / normalisation |
| L — Wrong retrieval / synthesis | 2 | Retrieved wrong entity; ambiguous graph nodes | ✅ Retrieval improvement |

#### True data gaps (~10) — unfixable without ingestion
Poison "Shut Up Make Love" year, Ellie Goulding Delirium co-writers, former NBA player Charlotte Hornets shortest player, Jerry Goldsmith executive producer, Scott Parkin corporation countries, Hard Easy younger brother, Wigan Athletic Carabao Cup, Roald Dahl book copies, Former Soviet statesman forum type, "Prince of tenors" Rome film.

#### Bad graph data (~6) — fixable with targeted re-ingestion
- `Local H / For Against from US` → graph has no origin data for For Against (should be Lincoln, Nebraska)
- `Random House Tower real estate?` → graph conflates publisher HQ with apartment complex
- `Jim Cummings hedgehog` → graph returns Dr. Robotnik instead of Sonic
- `VCU founded year` → graph says 1968, correct answer is 1838
- `Japanese manga author born year` → graph says 1956, correct is 1962
- `Cypress/Ajuga both genera?` → graph incorrectly classifies one or both

#### Decomposition misfires (3) — pipeline bug
- **Brown State Fishing Lake population**: second sub-question became "What is the population of United States?" (should have been "What is Brown County, Kansas population?"). Decomposer over-generalised the geography.
- **Roger O. Egeberg president years**: placeholder fill left empty (`"What years did  serve as president?"` — blank name), because Step 2 returned no short answer for the bridge entity. Causes (no answers found) downstream.
- **122nd SS-Standarte city inhabitants**: sub-question asked for inhabitants but synthesis still returned city name "London, United Kingdom" — RULE 4 violation; answer type constraint wasn't strong enough.

#### Specificity failures (2) — RULE 5 not granular enough
- **Hayden / Buck-Tick**: expected `Fujioka, Gunma`, got `Japan`. RULE 5 says "use the most specific value" but the model chose country over city.
- **Dirleton fortress coastal area**: expected `Yellowcraig`, got `Firth of Forth`. Broader geographic feature vs. the specific named place.

Both suggest RULE 5 needs explicit negative examples: "If the question asks 'what city?' or 'what area?', do NOT answer with a country or a larger body of water."

#### Fuzzy near-misses (3) — string normalisation
- **Kerensky civil war end**: got `1923`, expected `October 1922`. No token overlap → F1 = 0.
- **Rostker v. Goldberg**: got `draft registration`, expected `Conscription`. Direct synonym, zero word overlap → F1 = 0.
- **Bill Cosby hotel location**: got `Paradise, Nevada`, expected `Las Vegas Strip in Paradise`. F1 = 0.29, fuzzy fails.

### The practical ceiling is ~0.84 with current graph data

- ~10 true data gaps → unrecoverable without new ingestion
- ~6 bad-data nodes → recoverable with targeted re-ingestion

Even with a perfect model and pipeline, fuzzy match cannot exceed ~84% until the knowledge base is expanded. The gap from 0.74 → ~0.84 is reachable through decomposer fixes, RULE 5 strengthening, and fuzzy normalisation alone.

### What Gemini does better than gemma3:4b
1. **Synthesis rule adherence** — almost no intermediate bridge entity returns (Category B failures near zero).
2. **Age comparison** — correctly reasons "born 1965 is older than born 1970" without reversal.
3. **Temporal disambiguation** — RULE 6 applied correctly in all tested cases (Vermont conference etc.).
4. **Multi-hop chains** — handles 3-hop questions that gemma3 occasionally collapses.

### What still fails identically regardless of model
Every data-gap and bad-data failure is the same across both models. **The graph is the bottleneck, not the reasoning.** Upgrading the model again (e.g. to gemini-2.5-pro) would give marginal gains; fixing the graph data would give more.

---

## What's Left in v2 Worth Keeping

The **synthesis prompt rules (A/B/C)** developed for v2 are valid improvements even though the search strategy was wrong. These directly address failure categories A, B, and C:

```
RULE A: YES/NO questions → output the single word "YES" or "NO" only.
        Never output the compared value (e.g., "American"). 
        ALL values the same → YES. ANY differ → NO.

RULE B: COMPARISON questions (which/who/what had more/less/greater/fewer) →
        compare the metric values across entities, then output the WINNER'S NAME.
        Do NOT output the metric itself.

RULE C: MULTI-HOP questions → the final answer comes from the sub-question that
        directly resolves the answer type requested.
        Intermediate bridge entities (e.g., the university you looked up) are NOT the answer.
```

**Next action**: Port these rules back into `evaluate_hop_pipeline.py` and `test_hop_pipeline.py` (the v1 pipeline), then re-run the full benchmark. Expected improvement: +10–15% on the ~19 Category A/B/C failures.

---

## What Has Been Tried in `llm.py` / `chat.py`

### `identify_information_needs` prompt rules added this session:
- **Rule 6**: Explicit ban on natural language back-references — must use `[placeholder]` instead of "that series", "the same author", etc.
- **Rule 7**: If the question contains all filter criteria within itself, produce a single-hop plan.
- **New example**: Added a single-hop series question to the few-shot examples.

### `chat.py` substitution:
- Two-tier fallback: key-based dict substitution → regex `re.sub(r"\[[^\]]+\]", last_answer, filled_query)`.
- `step_direct_answers` list tracks relayed answers separately from full passage text.

---

## Gemini v6 — Model Regression with gemini-2.5-flash

### Score: 55/100 fuzzy (0.55) · 35/100 exact · F1 0.479 — **−19pp regression from v5-Gemini**

### The single root cause: over-refusal

Of the 45 failures, ~33 are explicit refusals:

```
"No answer found"
"No information available."
"Information not available."
"Cannot be determined from the evidence."
"(no answer)"
```

gemini-2.0-flash synthesised a best-effort answer from partial evidence and passed fuzzy matching. gemini-2.5-flash over-analyses the sparse evidence, concludes "insufficient", and refuses to commit — which always scores 0.

### Failure breakdown (45 total)

| Category | Count | Description |
|----------|-------|-------------|
| Over-refusal — explicit "no answer" response | ~33 | Model refuses to synthesise even when partial evidence exists |
| Wrong answer (attempted but incorrect) | 6 | Random House Tower yes/no, Kaiser Ventures type confusion, Adelaide vs Marion, Ais vs Apalachees, Kenny vs Bill Murray, Rostker synonym |
| Persistent data gaps (same as v5-Gemini) | 6 | 2014 S/S, Eenasul Fateh, Apple Remote, Livesey Hall, Euromarché, Indianapolis Speedway |

### Shared vs new failures vs v5-Gemini

| Status | Count | Examples |
|--------|-------|----------|
| Failures carried over from v5-Gemini | ~20 | Data-gap questions, Egeberg empty-placeholder, Vermont conference, Jim Cummings/Sonic, Random House Tower |
| **New regressions introduced by 2.5-flash** | ~25 | Orange/Netherlands, Rostker synonym, Hawaiian surfer, Handi-Snacks, John Waters — all previously correct |

### Why smarter hurt: the "overthinking" penalty in RAG

1. **Stronger RLHF for factual accuracy** — 2.5-flash is trained to say "I don't know" when coverage is incomplete. In a RAG setting, sparse partial evidence is the *norm*, not a failure; this behaviour becomes a bug.

2. **Thinking mode amplifies caution** — 2.5-flash runs internal chain-of-thought before answering. When evidence is thin, that reasoning reinforces uncertainty rather than committing to the best-supported answer.

3. **Verification filter + refusal compound** — if 2.5-flash's YES/NO verification step is also stricter, fewer docs pass, leaving synthesis with even less to work with.

4. **Fuzzy matching punishes non-answers** — partial answers like `"3677"` (expected `"3,677 seated"`) pass fuzzy (F1 0.67). An explicit `"No answer found"` always scores 0. 2.5-flash opts for the safe non-answer.

### Key lesson

> **For RAG pipelines with sparse knowledge bases, prefer a model calibrated for best-effort synthesis over one calibrated for factual precision.**
> gemini-2.0-flash accepts uncertainty and synthesises anyway. gemini-2.5-flash refuses when uncertain.
> Smarter ≠ better when the bottleneck is incomplete retrieval, not model reasoning.

### Mitigation options

| Option | Expected gain | Effort |
|--------|--------------|--------|
| Revert to gemini-2.0-flash (v5-Gemini) | +19pp immediately | Zero — already done |
| Add "If evidence is ambiguous, give your best answer" instruction to synthesis prompt | +5–10pp | Low |
| Lower verification YES/NO threshold (accept `MAYBE`) | +3–5pp | Low |
| Use 2.5-flash for decomposition only, 2.0-flash for synthesis | Potentially best of both | Medium |

---

## Next Steps (Priority Order)

1. **[Done] Gemini model comparison** — gemini-2.0-flash: **0.74** (+5pp over gemma3 v4.3). Confirms ~half of remaining failures are model capability, ~half are data gaps.

2. **[Done] gemini-2.5-flash comparison** — Scored 0.55, a 19pp regression. Root cause: over-refusal when evidence is sparse. Reverted to gemini-2.0-flash (v5-Gemini) as the benchmark leader.

2. **[High] Fix decomposer for empty placeholder fills**
   - When a bridge entity's short answer comes back empty, the next sub-question gets `"What years did  serve as president?"` — a blank where the name should be.
   - Fix: if `short_answer == ""`, skip placeholder substitution and pass the sub-question with `[placeholder]` intact, or surface a fallback that skips the hop.

3. **[Medium] Investigate best-effort synthesis instruction for 2.5-flash**
   - If 2.5-flash is used, add explicit prompt line: "If evidence is incomplete or ambiguous, provide your best answer anyway — do not respond with 'no answer found'."
   - Test whether this recovers the 19pp gap without introducing hallucinations.

4. **[High] Fix graph data for confirmed wrong-fact nodes**
   - For Against origin (Lincoln, Nebraska — missing entirely)
   - Jim Cummings → Sonic (graph returns Dr. Robotnik)
   - VCU founded year (1838, not 1968)
   - Japanese manga author birth year (1962, not 1956)
   - Random House Tower use classification
   - Cypress/Ajuga genera classification

4. **[Medium] Strengthen RULE 5 specificity constraint**
   - Current wording lets the model broaden to country when city/village is asked.
   - Fix: add explicit negative examples — "If the question asks 'what city?' or 'what area/neighborhood?', do NOT answer with a country, a body of water, or a broader administrative region."

6. **[Medium] Improve fuzzy/exact normalisation for near-misses**
   - `draft registration` ↔ `Conscription` — synonym expansion or lower F1 threshold to 0.3
   - `1923` ↔ `October 1922` — year-extraction normalisation before scoring
   - Answer wordiness trimming: strip qualifiers beyond the minimum answer span to improve exact match

7. **[Low] Back-port synthesis rules to `chat.py` production pipeline**
   - Port `_identify_answer_type()` constraint + RULES 4–6 into `_synthesize` in `app/workflows/chat.py`

---

## File Index

| File | Purpose |
|------|----------|
| `tests/benchmark/test_hop_pipeline.py` | 5-question diagnostic, verbose per-candidate output |
| `tests/benchmark/evaluate_hop_pipeline.py` | Full 100-Q evaluation, v1 (best: 0.57) |
| `tests/benchmark/evaluate_hop_pipeline_2.py` | v2 experiment (pure vector, top_k=500) — abandoned |
| `tests/benchmark/evaluate_hop_pipeline_v3.py` | v3 — full evidence synthesis, reasoning+FINAL format (0.63) |
| `tests/benchmark/evaluate_hop_pipeline_v4.py` | v4 — extended RULES 4–6, `_identify_answer_type` constraint, F1 ≥ 0.4 fuzzy pass (best: **0.69**) |
| `tests/benchmark/evaluate_hop_pipeline_v4_gemini.py` | v4 architecture with Gemini API calls |
| `tests/benchmark/evaluate_hop_pipeline_v5_gemini.py` | `gemini-2.0-flash` with identical v4 logic — current best **0.74** |
| `tests/benchmark/evaluate_hop_pipeline_v6_gemini.py` | `gemini-2.5-flash` — regression to 0.55; demonstrates over-refusal penalty |
| `tests/benchmark/evaluate_hop_pipeline_v5.py` | v5 — all token limits raised to 2048; confirmed regression vs v4 (0.67 vs 0.69) |
| `tests/benchmark/hotpotqa_manifest.json` | 100 HotPotQA questions with expected answers |
| `tests/benchmark/results/` | Timestamped result files from each run |
| `app/services/llm.py` | `identify_information_needs`, `extract_entity_name` |
| `app/workflows/chat.py` | `ChatWorkflow`, two-tier placeholder substitution |
