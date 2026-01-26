# Knowledge Graph Enhancement Plan

## Current State Assessment

### What's Working Excellently

- **Retrieval Quality**: After bug fix, LLM responses contain specific quotes and details
- **Weighted Scoring**: 5 boost factors operational (recency, entity, keyword, temporal, combined)
- **Dynamic Cutoffs**: Query-aware filtering (7.0/5.0/6.0 by type)
- **Performance**: 67.34s avg retrieval, 28.2 avg results (23% token reduction)
- **Accuracy**: Votex365 queries 100% relevance, livecops queries 50% relevance (up from 10%)

### Critical Gaps Identified

#### 1. Missing Inter-Node Relationships (BIGGEST GAP)

**Current**: Only Note→Node relationships exist

- Notes create Concepts, Entities, Tasks, People, Events
- Each node has summarized information
- No connections between the nodes themselves

**Missing**: Any-to-Any node relationships across all types:

- Concept ↔ Concept, Entity, Task, Person, Event
- Entity ↔ Concept, Entity, Task, Person, Event
- Task ↔ Concept, Entity, Task, Person, Event
- Person ↔ Concept, Entity, Task, Person, Event
- Event ↔ Concept, Entity, Task, Person, Event

**Impact**: System is a "note index with summaries" not a "knowledge graph with reasoning"

#### 2. Domain Metadata Underutilized

**Current**: Domains detected and stored but not used for:

- Filtering (show only Professional domain for work queries)
- Boosting (increase scores for domain-matched concepts)
- Context separation (prevent personal/work bleed)

#### 3. Performance Bottlenecks

**Ingestion**: 78-175s per note

- Sequential summarization (N LLM calls for N nodes)
- Full summary regeneration instead of incremental updates

**Retrieval**: 36-147s per query

- Reranking is 136s of 147s (93% of total time)
- Processing all candidates (no pre-filtering)

#### 4. Summarization Strategy

**Current Issues**:

- Sequential: Process one node at a time
- Full regeneration: Merge all related notes + call LLM
- No batching: Each update is separate LLM call

## High-Priority Improvements

### Priority 1: Add Inter-Node Relationships

#### Goal

Transform from "note index" to "true knowledge graph" with reasoning capabilities

#### Implementation Strategy

**Phase 1: Flexible Relationship Schema**

```python
# Universal relationship types (any node → any node)
RELATIONSHIP_TYPES = [
    # Structural
    "part_of", "contains", "composed_of",

    # Dependency & Sequence
    "depends_on", "blocks", "prerequisite_for", "enables", "leads_to",

    # Association & Reference
    "related_to", "references", "mentioned_in", "associated_with",

    # Ownership & Responsibility
    "owns", "created_by", "responsible_for", "assigned_to", "manages",

    # Collaboration & Social
    "works_with", "collaborates_with", "reports_to", "mentors", "knows",
    "friends_with", "married_to", "partners_with",

    # Functional & Implementation
    "implements", "uses", "affects", "modifies", "produces",

    # Temporal & Causation
    "triggered_by", "caused_by", "resulted_in", "preceded_by", "followed_by",

    # Semantic & Knowledge
    "contradicts", "supports", "validates", "demonstrates", "exemplifies",
    "expert_in", "learning", "teaches",

    # Task & Project
    "subtask_of", "milestone_for", "deliverable_of"
]

# Common relationship patterns (examples, not exhaustive):
COMMON_PATTERNS = {
    "Person→Person": ["knows", "friends_with", "married_to", "works_with",
                      "reports_to", "mentors", "collaborates_with", "partners_with"],
    "Person→Task": ["assigned_to", "responsible_for", "owns", "created_by"],
    "Person→Entity": ["works_on", "owns", "manages", "created_by"],
    "Person→Concept": ["expert_in", "learning", "teaches"],

    "Task→Task": ["depends_on", "blocks", "subtask_of", "related_to"],
    "Task→Entity": ["uses", "modifies", "affects", "implements"],
    "Task→Concept": ["implements", "demonstrates", "requires"],

    "Entity→Entity": ["depends_on", "uses", "integrates_with", "part_of"],
    "Entity→Concept": ["implements", "based_on", "uses", "demonstrates"],

    "Concept→Concept": ["prerequisite_for", "related_to", "contradicts", "part_of", "supports"],
    "Concept→Entity": ["implemented_by", "used_in", "demonstrated_by"],

    "Event→Any": ["triggered_by", "resulted_in", "involves", "demonstrates", "introduced"]
}
```

**Phase 2: Relationship Extraction & Evolution**

- Enhance LLM extraction to identify ANY meaningful connection between nodes
- Extract during ingestion with flexible pattern matching:
  - "X is prerequisite for Y" → (X)-[prerequisite_for]→(Y)
  - "Person A works with Person B on Entity C" → (A)-[works_with]→(B), (A)-[works_on]→(C), (B)-[works_on]→(C)
  - "Task X blocks Task Y" → (X)-[blocks]→(Y)
  - "Entity A implements Concept B" → (A)-[implements]→(B)
  - "Person A and Person B are friends" → (A)-[friends_with]→(B)
- **Relationship Evolution**: Update relationships as they change over time:
  - "Person A married Person B" → Update (A)-[friends_with]→(B) to (A)-[married_to]→(B)
  - Keep historical record: store previous relationship type in `previous_type` property
  - Track transition date in `relationship_changed` property
- Store in Neo4j with rich properties:
  - `confidence` (0.0-1.0): extraction confidence score
  - `first_seen` (date): when relationship first detected
  - `last_updated` (date): most recent mention
  - `relationship_changed` (date): when relationship type last changed
  - `previous_type` (string): previous relationship type before evolution
  - `mention_count` (int): # of notes mentioning this relationship
  - `context` (text): sample phrase showing the relationship
  - `is_active` (bool): whether relationship is still current

**Phase 3: Retrieval Integration**

- Graph traversal: When retrieving Concept X, also fetch related concepts
- Relationship scoring: Weight relationships by type and confidence
- Context enrichment: Include connected nodes in LLM context

**Expected Impact**:

- Richer context for LLM (concepts with their prerequisites/dependencies)
- Better reasoning ("Can't discuss X without understanding Y first")
- True knowledge graph queries ("Show me all entities Person A works on")

### Priority 2: Retrieval Performance Optimization

#### Goal

Reduce retrieval latency from 36-147s to <30s through parallel processing and lighter models

#### Current Bottleneck

```
Query Processing Timeline:
- Candidate collection: 5-10s
- Reranking 134-190 candidates: 70-136s (93% of total time)
- LLM synthesis: 5-8s

Total: 80-154s
```

**Problem**: Sequential reranking with heavy model (`mxbai-rerank-large-v2-seq`) is slow

#### Implementation Strategy

**Phase 1: Test Lightweight Reranker**

```python
# Current: Heavy reranker
MODEL_RERANKER = "mxbai-rerank-large-v2-seq"  # Large, accurate, slow

# Test: Ollama-based embedding model as reranker
MODEL_RERANKER_OLLAMA = "qwen3-embedding:0.6b"  # Small, fast, already downloaded

# Implementation
class OllamaReranker:
    """Use Ollama embedding model for reranking via cosine similarity"""

    async def rerank(self, query: str, candidates: List[str]) -> List[Dict]:
        # Get query embedding
        query_emb = await self.ollama.embed(query)

        # Get candidate embeddings in parallel batches
        candidate_embs = await self._batch_embed(candidates, batch_size=32)

        # Calculate cosine similarity scores
        scores = [cosine_similarity(query_emb, cand_emb) for cand_emb in candidate_embs]

        # Return sorted by score
        return sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
```

**Expected Impact**:

- 60-70% faster reranking (90s → 25-30s)
- Test quality: If acceptable, keep; if degraded, try parallel approach with current model

**Phase 2: Parallel Reranking with Smaller Batches**

```python
async def parallel_rerank(self, query: str, candidates: List, batch_size=25):
    """
    Current: 187 candidates processed sequentially (slow path due to VRAM)
    Optimized: 4 batches of ~47 processed in parallel
    """
    # Split into batches
    batches = [candidates[i:i+batch_size] for i in range(0, len(candidates), batch_size)]

    # Rerank batches concurrently
    tasks = [self.reranker.rerank(query, batch) for batch in batches]
    batch_results = await asyncio.gather(*tasks)

    # Merge and re-sort by score
    all_results = [item for batch in batch_results for item in batch]
    return sorted(all_results, key=lambda x: x['score'], reverse=True)
```

**Expected Impact**:

- 40-50% faster if VRAM pressure is resolved
- Avoids sequential fallback path

**Phase 3: Database Query Optimization**

```python
# Before: Potential N+1 query pattern
for note_id in note_ids:
    note = await db.get_note(note_id)  # Separate query each

# After: Batch fetch
notes = await db.get_notes_batch(note_ids)  # Single query with IN clause

# Add query timing instrumentation
@log_timing
async def get_notes_batch(self, note_ids: List[str]) -> List[Note]:
    """Fetch multiple notes in single query"""
    query = select(Note).where(Note.id.in_(note_ids))
    result = await self.session.execute(query)
    return result.scalars().all()
```

**Expected Impact**:

- If DB queries are slow: 20-30% faster retrieval
- If already optimized: No change (baseline measurement)

**Phase 4: Future Optimization (Post-Testing)**

_Only implement if lightweight reranker + parallel processing insufficient_

- Pre-filter candidates to top 75 before reranking
- Limit graph node expansion (2-3 notes per node instead of unlimited)
- Skip reranking for simple entity/temporal queries

#### Testing Plan

1. **Baseline**: Measure current performance with timing logs
2. **Test A**: Switch to `qwen3-embedding:0.6b` reranker
   - Measure: Speed improvement
   - Measure: Quality (compare top-10 results with current)
3. **Test B**: Add parallel reranking (with current or new model)
   - Measure: VRAM usage, speed improvement
4. **Test C**: Database query optimization
   - Add timing logs to measure impact
5. **Decision**: Keep best combination

#### Success Criteria

- **Performance**: <30s average retrieval time (from 67s)
- **Quality**: Top-10 relevance maintained at ≥90%
- **Reliability**: No VRAM errors, consistent performance

### Priority 3: Batch Summarization Updates

#### Current Flow

```
New note ingested → Extract 5 concepts
For each concept:
  - Fetch related notes
  - Merge all content
  - Call LLM to generate summary
Total: 5 LLM calls
```

#### Proposed Flow

```
New note ingested → Extract 5 concepts
Batch prepare:
  - For each concept, fetch related notes and prepare context
  - Create single prompt with all 5 concepts
  - One LLM call generates all 5 summaries
Total: 1 LLM call
```

**Implementation**:

```python
async def batch_update_summaries(node_updates: List[Dict]) -> Dict[str, str]:
    """
    Generate multiple node summaries in single LLM call

    Args:
        node_updates: [{"node_id": "X", "label": "Concept", "related_notes": [...]}]

    Returns:
        {"node_id_1": "updated summary", "node_id_2": "updated summary", ...}
    """
    # Build batch prompt with all contexts
    # Single LLM call with structured output
    # Parse results and update all nodes
```

**Expected Impact**:

- 5x faster ingestion (1 call vs 5 calls)
- Cost reduction (batched inference cheaper)
- Better cross-concept awareness (LLM sees all concepts together)

## Medium-Priority Improvements

### Priority 4: Domain-Aware Retrieval

**Implementation**:

```python
def _calculate_domain_boost(node_domain: str, query_domain: str) -> float:
    """
    Boost nodes matching query domain

    Professional query + Professional node → 2.0x boost
    Personal query + Professional node → 0.8x penalty
    """
    if node_domain == query_domain:
        return 2.0
    elif query_domain and node_domain != query_domain:
        return 0.8
    return 1.0
```

**Expected Impact**:

- Better context separation (work vs personal)
- More relevant results for domain-specific queries
- Reduced noise from cross-domain contamination

### Priority 5: Incremental Summary Updates

**Current**: Regenerate full summary from all related notes
**Proposed**: Update existing summary with new information

**Implementation**:

```python
async def incremental_update_summary(
    node_id: str,
    current_summary: str,
    new_notes: List[str]
) -> str:
    """
    Update existing summary with new information instead of regenerating

    Prompt: "Given this summary: {current_summary}
            And these new notes: {new_notes}
            Update the summary to incorporate new information while preserving existing insights"
    """
```

**Expected Impact**:

- Faster updates (shorter LLM context)
- Preserved quality (don't lose good existing summaries)
- Better summary stability (fewer dramatic changes)

## Implementation Sequence

### Week 1: Foundation

1. Design inter-node relationship schema
2. Update Neo4j models with new relationship types
3. Enhance extraction prompts to identify relationships
4. Add relationship storage in graph_service.py

### Week 2: Retrieval Performance & Extraction

1. Test lightweight reranker (qwen3-embedding:0.6b)
2. Implement parallel reranking
3. Optimize database queries with timing instrumentation
4. Measure performance improvements
5. Begin relationship extraction in LLM service
6. Add relationship queries to graph_service.py

### Week 3: Retrieval Integration

1. Implement graph traversal in retrieval_service.py
2. Add relationship-aware context formatting
3. Test with sample queries
4. Measure quality improvement

### Week 4: Domain & Summary Optimizations

1. Implement batch summarization (Priority 3)
2. Add domain-aware retrieval boosting (Priority 4)
3. Implement incremental summary updates (Priority 5)
4. Performance testing and tuning
5. Documentation updates

## Success Metrics

### Quality Metrics

- **Relationship Coverage**: % of concepts with inter-node relationships
- **Retrieval Relevance**: % of top-10 results rated highly relevant
- **Context Richness**: Avg # of related concepts included in LLM context

### Performance Metrics

- **Ingestion Time**: Target 30-50s (from 78-175s) via batch summarization
- **Retrieval Time**: Target <30s (from 36-147s) via lightweight reranker + parallel processing
- **Reranking Time**: Target 15-25s (from 70-136s) via qwen3-embedding + parallelization

### User Experience

- **Response Quality**: Specific quotes + relationship awareness
- **Cross-Reference Accuracy**: Correctly identifies prerequisites/dependencies
- **Domain Separation**: No personal context in work queries

## Open Questions

1. **Relationship Confidence**: How to score extraction confidence? (0.0-1.0 scale)
2. **Relationship Evolution**: When to update vs create new relationship? (friends→married updates, works_with→reports_to might be separate)
3. **Relationship History**: Keep full history or just previous state?
4. **Circular Dependencies**: How to handle Concept A→B→C→A loops?
5. **Relationship Limits**: Max relationships per node? (prevent over-connection)
6. **Batch Size**: Optimal number of summaries per LLM call? (5? 10? 20?)
7. **Bidirectional Storage**: Store both A→B and B←A or infer inverse?
8. **Relationship Weights**: Should some relationship types be stronger in graph traversal?
9. **Reranker Quality Trade-off**: Is qwen3-embedding quality acceptable vs speed gain?
10. **Candidate Limiting**: If reranker optimization insufficient, limit candidates to 75 or 50?
11. **Caching Strategy**: After testing complete, cache reranked results? (LRU cache, similarity threshold?)

## Risk Mitigation

### Risk: Over-connected Graph

**Mitigation**:

- Confidence thresholds (only store high-confidence relationships)
- Relationship limits per node (max 10-15 relationships)
- Periodic pruning of low-confidence connections

### Risk: Extraction Errors

**Mitigation**:

- Human review for first 100 relationships
- Confidence scoring with manual override
- Easy deletion/correction UI

### Risk: Performance Regression

**Mitigation**:

- Feature flags for gradual rollout
- Performance monitoring at each stage
- Rollback plan if metrics degrade

### Risk: Summary Quality Degradation

**Mitigation**:

- A/B test batch vs individual summaries
- Quality review on sample set
- Fallback to individual if batch quality poor

## Next Steps

**Immediate**:

1. Review and refine this plan
2. Choose starting point (Priority 1 or 2?)
3. Set up development branch
4. Create detailed technical spec for chosen priority

**This Week**:

- If Priority 1: Design flexible relationship schema, update Neo4j models, add evolution logic
- If Priority 2: Test qwen3-embedding reranker, implement parallel reranking, measure improvements
- If Priority 3: Prototype batch summarization with structured output

**This Month**:

- Complete Priority 1 implementation (inter-node relationships with evolution)
- Complete Priority 2 implementation (retrieval performance optimization)
- Complete Priority 3 implementation (batch summarization)
- Begin Priority 4-5 (domain-aware retrieval, incremental summaries)
- Measure and document improvements
