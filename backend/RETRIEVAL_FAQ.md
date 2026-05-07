# Retrieval System - Frequently Asked Questions

## Q1: How do community summaries and neighborhood summaries work?

### What They Are
In current ingestion, node updates are isolated-context-first. The update path accumulates source contexts for each node and keeps relationship structure current.

### How They Work

#### 1. **Initial Creation**
When a note is first ingested:
- Extraction returns nodes with `name`, `type`, and `isolated_context`
- Extraction also returns relationships, which are written to the graph and relationship index
- Node `description` is not part of the extraction payload

#### 2. **Incremental Updates** (`_update_neighborhoods`)
When a new note mentions existing entities:
- The `_update_neighborhoods()` path updates per-node isolated context storage for affected entities
- For each mentioned entity, it:
    1. **Fetches existing persisted content** for the entity
    2. **Extracts isolated context** for the new mention
    3. **Appends new isolated contexts** and embeds only those new contexts
    4. **Indexes context + relationship text** for retrieval

No description generation is performed in this update phase.

#### 3. **Usage in Retrieval**
When searching, retrieval can still use relationship evidence plus stored isolated contexts for node-level grounding.

Conceptually, updated node payload is closer to:
```python
text = f"contexts: {' '.join(isolated_contexts)} | relationships: {relationship_nl}"
```

### Example Flow
```
Note: "I'm working on Votex365 USSD integration"
↓
1. Find existing node "Votex365"
2. Extract context: "working on Votex365 USSD integration"
3. Append this isolated context for that node
4. Embed and persist the appended context
5. Keep relationship extraction/storage active for graph and relationship search
```

### How to Test Them
This now has direct unit coverage in addition to broader ingestion/retrieval checks:
1. **Ingestion tests** verify isolated contexts are appended and embedded on updates
2. **Retrieval tests** verify isolated contexts and relationship text surface as grounded evidence

To inspect it manually, check persisted entries in `node_isolated_contexts` and verify relationships still exist in graph + `node_relationships`.

---

## Q2: What is the maximum relevance score for each item?

### Score Components

Your system uses **multi-factor weighted scoring**:

```python
final_score = rerank_score × recency_boost × entity_boost × keyword_boost × temporal_boost
```

### Individual Score Ranges

| Component | Range | Notes |
|-----------|-------|-------|
| **Rerank Score** | 0.0 to ~10.0+ | From mxbai-rerank model. Typically 0-2 for irrelevant, 2-8 for relevant, 8-10+ for highly relevant |
| **Recency Boost** | 1.0 to 2.0 | Linear decay: 2.0x for today, 1.0x for old notes |
| **Entity Match Boost** | 1.0 or 2.0 | Binary: 2.0x if entity detected in text, 1.0x otherwise |
| **Keyword Match Boost** | 1.0 to 3.0 | Tiered: 3.0x for 80%+ match, 2.0x for 50%+, 1.5x for 30%+, 1.0x otherwise |
| **Temporal Query Boost** | 1.0 or 3.0 | Binary: 3.0x for recent notes on temporal queries, 1.0x otherwise |

### Theoretical Maximum Score
```
Max = 10.0 (rerank) × 2.0 (recency) × 2.0 (entity) × 3.0 (keyword) × 3.0 (temporal)
    = 10.0 × 2.0 × 2.0 × 3.0 × 3.0
    = 360.0
```

**In practice**:
- **Typical high-quality results**: 5-15
- **Excellent matches**: 15-30
- **Perfect storm** (all boosts): 50-100

From your test results:
- Query 1 (livecops): Top score = **9.40**
- Query 2 (Votex365): Top score = **10.23**
- Query 3 (recent notes): Top score = **7.98**
- Query 4 (recent thoughts): Top score = **7.67**

### Why Scores Vary
- **Entity queries** (Votex365): High rerank + entity boost + keyword boost = 10+
- **Temporal queries** (recent notes): Medium rerank + temporal boost = 7-8
- **Generic queries**: Moderate rerank + recency = 5-7

---

## Q3: What would be a good cutoff point to avoid feeding the LLM unnecessary information?

### Current System
Your system already has a **score threshold of 0.6** ([retrieval.py](retrieval.py#L312)):
```python
score_threshold = 0.6
if score < score_threshold:
    continue  # Skip low-quality results
```

This means only results with `final_score >= 0.6` are returned.

### Recommended Cutoff Strategies

#### Option 1: **Dynamic Top-K (Current Approach)**
```python
top_k = 25  # Return best 25 results
```
**Pros**: Simple, predictable context size
**Cons**: May include weak results if query has few good matches

#### Option 2: **Adaptive Score Threshold**
```python
# After sorting by final_score
cutoff_score = max(0.6, results[0].score * 0.5)  # At least 50% of top result
filtered = [r for r in results if r.score >= cutoff_score][:25]
```
**Pros**: Automatically adjusts to query difficulty
**Cons**: More complex logic

#### Option 3: **Percentile-Based (Recommended)**
```python
# Keep top 70th percentile
if len(results) > 10:
    scores = [r["final_score"] for r in results]
    p70 = np.percentile(scores, 70)
    filtered = [r for r in results if r["final_score"] >= p70][:25]
else:
    filtered = results[:10]
```
**Pros**: Adapts to result distribution, removes long tail
**Cons**: Requires numpy, more computation

#### Option 4: **Tiered Cutoffs by Query Type** ⭐ **BEST**
```python
if is_temporal_query:
    cutoff = 5.0  # Lower bar for temporal (need more recent context)
elif query_entities:
    cutoff = 7.0  # Higher bar for entity queries (precision over recall)
else:
    cutoff = 6.0  # Default for general queries

filtered = [r for r in results if r["final_score"] >= cutoff][:25]
```
**Pros**: 
- Optimized for each query type
- Balances precision and recall
- Based on your actual score distributions

**Cons**: Requires maintaining cutoff values

### Based on Your Test Data

Looking at your results:

| Query Type | Top Score | Avg Score | Recommended Cutoff |
|------------|-----------|-----------|-------------------|
| Entity (Votex365) | 10.23 | 8.67 | **7.0** (keep top 70%) |
| Entity (livecops) | 9.40 | 3.85 | **6.0** (avoid low-quality) |
| Temporal (recent notes) | 7.98 | 7.10 | **6.0** (keep most) |
| Temporal (recent thoughts) | 7.67 | 6.07 | **5.0** (broader context) |

### Recommended Implementation

Add to [retrieval.py](retrieval.py):

```python
def _get_cutoff_score(
    self,
    query: str,
    is_temporal_query: bool,
    query_entities: List[str],
    results: List[dict],
) -> float:
    """
    Determine dynamic cutoff score based on query type and result distribution.
    """
    if not results:
        return 0.6  # Minimum threshold

    top_score = results[0].get("final_score", 0)

    # Tiered cutoffs
    if query_entities:
        # Entity queries: High precision
        base_cutoff = 7.0
    elif is_temporal_query:
        # Temporal queries: Broader context
        base_cutoff = 5.0
    else:
        # General queries: Balanced
        base_cutoff = 6.0

    # Adaptive: If top score is low, lower the bar
    if top_score < base_cutoff:
        return max(0.6, top_score * 0.6)  # 60% of top score, min 0.6

    return base_cutoff


# Usage in hybrid_search():
all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

# Apply dynamic cutoff
cutoff = self._get_cutoff_score(query, is_temporal_query, query_entities, all_results)
filtered_results = [r for r in all_results if r.get("final_score", 0) >= cutoff]

# Then apply diversity constraint
final_list = self._apply_diversity_constraint(filtered_results, max_per_note=3)
```

### Context Size for LLM

Based on typical LLM context windows:

| Model | Context | Recommended Results | Tokens per Result | Total Tokens |
|-------|---------|---------------------|-------------------|--------------|
| GPT-4 | 8K-128K | 15-25 | ~200-400 | 3K-10K |
| Claude | 100K-200K | 25-50 | ~200-400 | 5K-20K |
| Llama 3 | 8K-128K | 15-25 | ~200-400 | 3K-10K |

**Recommendation**: 
- Keep **top 15-25 results** after applying cutoff
- This gives ~3-10K tokens of context (safe for most models)
- Apply diversity constraint to prevent redundancy

### Quick Wins for Your System

1. **Implement tiered cutoffs** (5 minutes):
   - Temporal: 5.0
   - Entity: 7.0  
   - General: 6.0

2. **Add score-based limit** (2 minutes):
   ```python
   final_list = [r for r in final_list if r["final_score"] >= cutoff][:25]
   ```

3. **Log cutoff decisions** (1 minute):
   ```python
   logger.info(
       f"Applied cutoff {cutoff:.2f}: {len(all_results)} → {len(filtered_results)} results"
   )
   ```

This will prevent feeding low-quality results (score < 5-7) to your LLM while maintaining good recall for different query types.

---

## Q4: Why did duplicate same-name nodes with empty content appear, and what was fixed?

### Root Cause
Duplicate same-name nodes with empty content were caused by an **ingestion identity mismatch** between Kuzu and Qdrant during summary updates:

- A node could already exist structurally in Kuzu.
- If Qdrant lookup missed that name in the summary stage, ingestion minted a new `node_id`.
- That produced another node with the same name, often with sparse or empty content initially.

### Fix Applied
Two changes were made to prevent this:

1. **Summary-stage ID reuse on Qdrant miss**:
    - If Qdrant misses, ingestion now checks Kuzu for an exact same-name `indexable` node.
    - When found, it reuses that existing Kuzu `node_id` instead of creating a new one.

2. **Paginated batch name lookup in Qdrant**:
    - `find_node_ids_by_names` now scrolls through pages (instead of relying on a single limited result set).
    - This avoids unresolved names when many same-name/duplicate candidates exist.

### Safe Cleanup Guidance
Do **not** bulk-delete all empty nodes.

- Many empty nodes may still carry graph edges and deleting them blindly can break traversal paths.
- Only empty nodes with **no incoming and no outgoing edges** are safe to delete directly.
- For empty nodes with edges, rewire/merge relationships first, then delete.

---

## Q5: What retrieval fixes were shipped in the latest remediation pass?

Two remediation passes were shipped in April 2026.

**Pass 1 — Stability fixes (three changes):**

1. **`select_relevant_docs_with_reasoning()` compatibility update**
    - The method now accepts `original_query`.
    - This lets sub-question filtering preserve full original question context, improving relevance decisions during multi-hop loops.

2. **Entity-first retrieval with guarded vector fallback**
    - Retrieval attempts entity-first evidence first.
    - Vector/full-text fallback is only used when entity matches do not provide usable text evidence.
    - This avoids unnecessary vector noise while still recovering when entity-only evidence is insufficient.

3. **One-hop graph expansion evaluation stability**
    - The one-hop graph expansion + LLM selection/evaluation stage is no longer failing in the latest benchmark run.

**Pass 2 — Pipeline hardening:**

1. **`hybrid_search` is entity-first** — entity lookup runs before any vector scan. Vector/full-text search is a fallback only, not the primary path.

2. **Pre-batch relationship cache (`_rel_cache`)** — relationships are fetched once per `hybrid_search` call (not per candidate), reducing graph round-trips and improving performance.

3. **Dead code removed from `retrieval.py`** — `_build_query_variants`, `_generate_rewritten_query`, and `_generate_step_back_query` were never called from any active code path and have been deleted.

4. **`query_decomposition.py` deleted** — this file was a legacy unused workflow and has been removed entirely. It is not part of the active chat pipeline.

5. **`retrieve_with_self_correction` is a compatibility stub** — it no longer triggers a self-correction loop; it delegates directly to the standard retrieval path.

6. **`_verify_candidates` removed from `chat.py`** — was dead code; `_extract_references` now uses only `linked_notes`.

7. **LLM contract fixes in `llm.py`**:
    - Yes/no normalization now matches a broader range of surface forms.
    - Multi-line `FULL_ANSWER` sections are parsed correctly.
    - A redundant LLM call in synthesis was eliminated via the `query_attr` parameter.

8. **Test suite expanded**: `backend/tests/unit/test_llm_contracts.py` now has 52 passing cases.

Latest benchmark artifact (Pass 1 smoke run):
- `backend/tests/benchmark/results/hotpotqa_n5_20260428_145930.json`

Top outcomes from that run (`n=5`):
- `error_count=0`
- `answer_exact_match=0.4`, `answer_f1=0.4`, `answer_fuzzy_match=0.4`
- `retrieval_precision=0.3848`, `retrieval_recall=0.7`, `retrieval_f1=0.4966`
