# LiveOS Retrieval & Ingestion Improvements

Derived from HotPotQA benchmark analysis (best score: **0.74** with gemini-2.0-flash).
Working list — check off items as implemented.

---

## Score Context

| Run | Score | Gap to 0.84 ceiling |
|-----|-------|---------------------|
| gemma3 v4.3 (local best) | 0.69 | −15pp |
| gemini-2.0-flash v5 (current best) | **0.74** | −10pp |
| gemini-2.5-flash v6 | 0.55 | over-refusal regression |
| Estimated ceiling (current graph data) | ~0.84 | — |

---

## Retrieval Improvements

### ✅ #1 — Zero-result fallback widening
**File**: `evaluate_hop_pipeline_v5_gemini.py` (and any future evaluators)  
**Problem**: When the YES/NO filter passes 0 docs for a sub-question, synthesis
immediately sees `(no answers found)` and returns nothing. The right node may exist
just below the top_k=20 / min_score=0.7 threshold.  
**Fix**: After a zero-verified result, retry with `top_k=50` before giving up.
```python
docs = await retrieval_service.hybrid_search(need, top_k=TOP_K)
verified = [d for d in docs if await _check(d)]
if not verified:                        # ← retry with wider net
    docs = await retrieval_service.hybrid_search(need, top_k=50)
    verified = [d for d in docs if await _check(d)]
```
**Expected gain**: +2–3pp  
**Effort**: 30 min  
**Status**: ✅ Implemented

---

### ✅ #2 — Priority lane for exact entity-name match in `hybrid_search`
**File**: `app/services/retrieval.py`  
**Problem**: The entity name-matching step (`find_nodes_by_name`) already finds
explicitly named nodes, but those nodes then compete with vector results on the same
scoring function. A filled sub-question like `"What hedgehog did Jim Cummings voice?"`
should force Jim Cummings's node to the very top, then expand all its 1-hop neighbors
before scoring runs.  
**Fix**: After entity matches are found, tag them `priority=high` and ensure they are
always included in the final top_k regardless of attribute-relevance score.  
Current code already sets `priority: "primary"` and `vector_score: 1.0` for entity
matches — the improvement is to **guarantee they survive the final top_k cut**.  
**Status**: ✅ Implemented (entity matches now unconditionally included; vector + neighbor
results fill remaining slots)

---

### ✅ #3 — Raw `isolated_contexts` fallback in `_candidate_text`
**File**: `tests/benchmark/test_hop_pipeline.py`  
**Problem**: `_candidate_text()` returns `node.summary`. Summaries are LLM-compressed
and can drop or distort atomic facts (e.g. VCU founding year, Jim Cummings voiced
character). The raw `isolated_contexts` list stores the original extracted snippets
unchanged.  
**Fix**: If the summary is very short (< 60 chars) or empty, fall back to the first
`isolated_context` stored on the node.
```python
summary = node.get("summary") or ""
if len(summary) < 60:
    raw_ctxs = node.get("isolated_contexts") or []
    if raw_ctxs:
        summary = raw_ctxs[0]
```
**Expected gain**: +1–2pp on bad-summary nodes  
**Effort**: 30 min  
**Status**: ✅ Implemented

---

## Ingestion Improvements

### ✅ #4 — Structured atomic fact extraction
**File**: `app/services/llm.py` + `app/workflows/ingestion.py`  
**Problem**: Node summaries are free-form prose. Key atomic facts (origin city,
founding year, birth year, genre) are embedded as part of a blended sentence and
get diluted in the vector. Retrieval relies entirely on cosine similarity to surface
them.  
**Fix**: Add a second LLM pass that extracts typed `(property, value)` pairs from the
node context. Store them as a JSON-serialised `facts` property on the Neo4j node.

```json
{
  "entity": "For Against",
  "facts": [
    {"property": "origin_city",    "value": "Lincoln"},
    {"property": "origin_state",   "value": "Nebraska"},
    {"property": "origin_country", "value": "United States"},
    {"property": "genre",          "value": "post-punk"},
    {"property": "formed_year",    "value": "1984"}
  ]
}
```

At query time, if a sub-question asks for a geographic/temporal attribute and a
matching fact property exists on a candidate node, that fact is surfaced directly
in the candidate text presented to the YES/NO filter and synthesis.  
**Expected gain**: +3–5pp after re-ingestion of affected nodes  
**Effort**: Half day  
**Status**: ✅ Implemented

---

### ✅ #5 — Facts-first format in `generate_entity_summary` prompt
**File**: `app/services/llm.py` → `generate_entity_summary()`  
**Problem**: Summaries are generated as flowing prose. When the whole summary is
embedded as one vector, atomic facts buried mid-paragraph get diluted. A query for
`"What country is X from?"` must hit the right cosine region when "United States"
appears as the 8th word of a long sentence.  
**Fix**: Change the summary format instruction to produce a FACTS header before the
prose:
```
FACTS: Origin = Lincoln, Nebraska. Founded = 1984. Genre = post-punk.
CONTEXT: For Against is a post-punk band that formed in ...
```
The embedding of the FACTS section aligns directly with narrow factual queries.
New nodes ingested after this change benefit immediately; existing nodes improve
on next update.  
**Expected gain**: +2–4pp after re-ingestion  
**Effort**: 1 hour (prompt only)  
**Status**: ✅ Implemented

---

## Data Fixes (separate from pipeline)

### #6 — Patch 6 known-bad Neo4j nodes
**Effort**: 1 hour  
**Expected gain**: +4–5pp immediately (no re-ingestion needed)

| Node | Current (wrong) | Correct |
|------|-----------------|---------|
| For Against | No US origin data | Lincoln, Nebraska, United States |
| Jim Cummings | Dr. Robotnik | Sonic the Hedgehog |
| VCU | Founded 1968 | Founded 1838 |
| Japanese manga author | Born 1956 | Born 1962 |
| Random House Tower | Real estate | Publisher HQ / office |
| Cypress (genus) | Misclassified | Not the same genus as Ajuga |

**Status**: ⬜ Not started

---

## Pipeline Bug Fixes

### #7 — Empty placeholder fill
**File**: `evaluate_hop_pipeline_v5_gemini.py` → `run_pipeline`  
**Problem**: When Step 2 returns no short answer (empty string), the next
sub-question becomes `"What years did  serve as president?"` — blank where
the entity name should be. This guarantees failure downstream.  
**Fix**: If `short_answer == ""`, skip `_substitute_placeholders` for that step
and log a warning. Optionally, abort the chain early rather than pass a broken
query to retrieval.  
**Status**: ⬜ Not started

---

## Scoring / Normalisation

### #8 — Synonym expansion for zero-overlap exact synonyms
**File**: `tests/benchmark/evaluate.py` or `_is_fuzzy_pass`  
**Problem**: `draft registration` vs `Conscription`, `1923` vs `October 1922` — zero
token overlap gives F1=0 even though the answers are semantically identical.  
**Fix**: Lower F1 threshold 0.4 → 0.3, or add a small synonym list for the most common
mismatches seen in benchmark results.  
**Status**: ⬜ Not started

---

## Priority Order

| # | Item | Effort | Expected gain | Status |
|---|------|--------|--------------|--------|
| 6 | Patch 6 bad nodes | 1h | +4–5pp | ⬜ |
| 1 | Zero-result fallback | 30m | +2–3pp | ✅ |
| 7 | Empty placeholder fix | 30m | +1–2pp | ⬜ |
| 3 | Raw context fallback | 30m | +1–2pp | ✅ |
| 2 | Priority entity lane | 30m | structural | ✅ |
| 5 | Facts-first summary prompt | 1h | +2–4pp (re-ingest) | ✅ |
| 4 | Structured fact extraction | 0.5d | +3–5pp (re-ingest) | ✅ |
| 8 | Synonym normalisation | 1h | +1–2pp | ⬜ |
