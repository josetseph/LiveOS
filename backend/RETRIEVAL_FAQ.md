# Retrieval System - Frequently Asked Questions

## Q1: How do community summaries and neighborhood summaries work?

### What They Are
In your system, **"neighborhood summaries"** refer to the **summary field on graph nodes** (Concepts, Entities, Tasks, Personas, References). There are no separate "community summaries" - the node summaries serve this purpose.

### How They Work

#### 1. **Initial Creation**
When a note is first ingested:
- Extracted entities (Concepts, Entities, Tasks, etc.) are stored as nodes in Neo4j
- Each node gets an initial `summary` field that describes it

#### 2. **Incremental Updates** (`_update_neighborhoods`)
When a new note mentions existing entities:
- The `_update_neighborhoods()` method in [ingestion.py](ingestion.py#L480) updates summaries
- For each mentioned entity, it:
  1. **Fetches existing summary** from Neo4j
  2. **Extracts context** - Gets text around the entity mention (±1 sentence window)
  3. **Calls LLM** - `llm_service.update_summary()` merges old summary + new context
  4. **Generates embedding** - Creates vector embedding from `title: summary`
  5. **Saves update** - Stores new summary, title, and embedding back to Neo4j

#### 3. **Usage in Retrieval**
When searching ([retrieval.py](retrieval.py#L251)):
```python
text = f"[{node_label}: {node_name}]: {node.summary}"
```
The summary is formatted as a text snippet and added to candidates for reranking.

### Example Flow
```
Note: "I'm working on Votex365 USSD integration"
↓
1. Find existing Concept node "Votex365" (has summary from past notes)
2. Extract context: "working on Votex365 USSD integration"
3. LLM updates summary:
   OLD: "A business platform for students"
   NEW: "A business platform for students. Recent work focuses on USSD integration."
4. Generate embedding for updated summary
5. Save to graph
```

### How to Test Them
Currently, neighborhood summaries are tested implicitly through:
1. **Ingestion tests** - Verify nodes are created with summaries
2. **Retrieval tests** - Check that graph nodes appear in results with `type: "graph_consensus"`

**To explicitly test summaries**:
```python
# Query a node's summary directly
result = graph_service.execute_query(
    "MATCH (n:Concept {name: $name}) RETURN n.summary, n.title",
    {"name": "Votex365"}
)
print(result[0]['summary'])
```

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
    scores = [r['final_score'] for r in results]
    p70 = np.percentile(scores, 70)
    filtered = [r for r in results if r['final_score'] >= p70][:25]
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

filtered = [r for r in results if r['final_score'] >= cutoff][:25]
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
def _get_cutoff_score(self, query: str, is_temporal_query: bool, 
                      query_entities: List[str], results: List[dict]) -> float:
    """
    Determine dynamic cutoff score based on query type and result distribution.
    """
    if not results:
        return 0.6  # Minimum threshold
    
    top_score = results[0].get('final_score', 0)
    
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
all_results.sort(key=lambda x: x.get('final_score', 0), reverse=True)

# Apply dynamic cutoff
cutoff = self._get_cutoff_score(query, is_temporal_query, query_entities, all_results)
filtered_results = [r for r in all_results if r.get('final_score', 0) >= cutoff]

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
   final_list = [r for r in final_list if r['final_score'] >= cutoff][:25]
   ```

3. **Log cutoff decisions** (1 minute):
   ```python
   logger.info(f"Applied cutoff {cutoff:.2f}: {len(all_results)} → {len(filtered_results)} results")
   ```

This will prevent feeding low-quality results (score < 5-7) to your LLM while maintaining good recall for different query types.
