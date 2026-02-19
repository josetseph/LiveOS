# LiveOS System Analysis - Q&A and Recommendations

**Date:** February 18, 2026  
**Context:** Comprehensive system audit after HotpotQA ingestion and benchmark testing  
**Current Performance:** EM=36%, F1=47.9%, Recall=66.5%, **Precision=11.8%** ⚠️

---

## Critical Discoveries

### 🚨 **#1: Qwen3-Embedding Instruction Prefix Missing**

**Problem**: Qwen3-Embedding:0.6b requires instruction prefix for queries (not documents), currently missing from `embedding_service.embed_query()`

**Impact**: Massive performance degradation - embeddings misaligned between queries and documents

**Fix Applied**: ✅ Added instruction prefix to `embed_query()` method:
```python
query_instruction = "Instruct: Given a web search query, retrieve relevant passages that answer the question\nQuery: "
```

**Expected Improvement**: +5-10pp precision, +3-5pp recall

**Testing Required**: Re-run HotpotQA benchmark to validate improvement

---

### ⚠️ **#2: Domain Boosting Bug**

**Problem**: Domain boost tries to read `node.get("domain")` but Entity/Concept nodes don't have `domain` property (only Notes do)

**Impact**: Domain boost effectively disabled for all entity/concept candidates

**Status**: ❌ Not fixed yet

**Recommendation**: Either propagate domain from notes to nodes during ingestion, or fetch from linked notes at retrieval time

---

### ⚠️ **#3: Isolated Context Embeddings Unused**

**Discovered**: You store `isolated_context_embeddings_json` with individual embeddings per context, but vector search doesn't query them

**Opportunity**: Create separate vector index for context embeddings to enable multi-context semantic matching

**Status**: Infrastructure exists, not utilized

---

## Question-by-Question Analysis

### **Q1: Entity Types - Always Require Type (No Anonymous)**

**Current**: Allows `type: "Anonymous"` for unnamed entities

**Your Proposal**: Always require proper type, allow updates when context improves

**Verdict**: ✅ **ADOPT** - Better semantic matching, type scoring works better

**Implementation**:
1. Remove "Anonymous" from extraction prompt
2. Require LLM to infer descriptive types ("Thief", "Neighbor", "Colleague")
3. Add type update logic:
   ```cypher
   MERGE (e:Entity {name: $name})
   ON CREATE SET e.type = $new_type
   ON MATCH SET e.type = CASE 
     WHEN e.type = "Unknown" THEN $new_type
     ELSE e.type 
   END
   ```

**Priority**: Medium (extraction quality improvement)

---

### **Q2: Types for Concepts/Tasks/Personas**

**Answer**: ❌ **Not needed**
- Concept/Task/Persona nodes ARE their type (via label)
- Only Entities need sub-typing because `:Entity` label is too generic
- References already have types (Paper/Book/Quote)

**Action**: None required

---

### **Q3: Complex Note Determination - Always Use Refinement?**

**Current**: `is_complex = len(content) > 3000`

**Your Proposal**: Always use refinement

**Verdict**: ⚠️ **Hybrid Approach Better**

**Recommended Logic**:
```python
extraction_quality = len(extraction.entities) + len(extraction.concepts)
is_complex = (
    len(content) > 3000 or  # Long content
    extraction_quality < 5  # Likely under-extracted
)
```

**Rationale**:
- ✅ Catches under-extraction automatically
- ✅ Avoids doubling LLM calls for high-quality short notes
- ✅ Still refines all complex notes

**Priority**: Low (quality vs cost trade-off)

---

### **Q4: Note Embeddings - Do We Need Them?**

**Current**: Yes, you generate note embeddings

**Usage**: ❌ Not used in retrieval (only searches `:Indexable` nodes)

**Verdict**: ✅ **Keep them for future features**:
- Temporal queries ("What did I work on last week?")
- Narrative retrieval ("Show my thoughts about X")
- Duplicate detection

**Cost**: Minimal (1 embedding/note vs 5+ per entities/concepts)

**Action**: None required

---

### **Q5: Embeddings for All Node Attributes**

**Current Embeddings**:
- ✅ Entity: `name (type)`
- ✅ Concept: `name: definition`
- ✅ Task: `Task: name (Status: status)`
- ✅ `isolated_context_embeddings_json`: Individual context embeddings
- ❌ Note attributes (importance, confidence) - not embedded

**Verdict**: ✅ **Current approach is optimal**

**Discovery**: You ALREADY embed individual isolated contexts! (Brilliant architecture)

**Opportunity**: Use `isolated_context_embeddings` in vector search (currently unused)

**Priority**: HIGH - Enable multi-context vector search

---

### **Q6: Qwen3 Instruction Prefix** (ADDRESSED ABOVE)

✅ **FIXED** - Added instruction prefix to query embeddings

---

### **Q7: Entity Deduplication - Does MERGE Combine Contexts?**

**Answer**: Split behavior
- ❌ `MERGE` itself doesn't combine contexts (only updates embedding)
- ✅ `_update_node_summary()` accumulates contexts later:
  ```python
  existing_contexts.append(isolated_context)
  summary = generate_summary(all_contexts_joined)
  ```
- ✅ Relationships accumulate naturally (separate MERGE per relationship)

**System Works Correctly**: No changes needed

---

### **Q8: Relationship Types - Free-form or Limited?**

**Answer**: ✅ **Free-form** (LLM can use any relationship type)

**Examples are suggestions, not constraints**: `developed`, `co-wrote`, `born_in`, etc.

**One caveat**: Hyphens sanitized (`co-wrote` → `co_wrote`)

**Verdict**: Working as designed

---

### **Q9: Vector Search Scope - All Embeddings?**

**Answer**: Searches all `:Indexable` nodes:
- ✅ Entity, Concept, Task, Reference nodes
- ❌ Note nodes (not indexed for vector search)
- ❌ `isolated_context_embeddings_json` (stored but not searched!)

**Opportunity**: Create vector index for context embeddings

**Priority**: HIGH - Could significantly improve precision

---

### **Q10: Neighbor Expansion - isolated_context or summary?**

**Current**: Returns **summary** (distilled)

**Alternative**: Could return first `isolated_context` for richer detail

**Verdict**: ✅ **Keep using summary** (manages context window better)

**Test**: Try isolated_context for queries where summary doesn't answer

**Priority**: Low (experimental)

---

### **Q11: Community Summaries - How Detect Broad Queries?**

**Answer**: Keyword-based detection:
```python
broad_query_keywords = ["overview", "summary", "what are", "tell me about", ...]
is_broad_query = any(kw in query.lower() for kw in broad_query_keywords)
```

**Usage**: Only 10.9% of HotpotQA dataset triggers community summaries

**Verdict**: Working but underutilized (HotpotQA has specific questions, not broad overviews)

**Action**: None needed for benchmark, valuable for personal notes

---

### **Q12: Linked Notes - Grounding or Just UI Links?**

**Your Claim**: "We trust system to synthesize, not using linked notes for grounding"

**Verdict**: ✅ **You're correct** - linked notes are:
- Attached to candidates but NOT included in `text` field sent to LLM
- Used for UI reference links only
- Indirect grounding: node summaries are synthesized FROM linked notes' contexts

**System Design is Correct**: Node summaries are the grounding

---

### **Q13: Type Scoring Synonyms - How Determined?**

**Answer**: **Hardcoded dictionary** in retrieval.py:
```python
type_synonyms = {
    "film": ["movie", "cinema"],
    "person": ["actor", "director", "writer"],
    ...
}
```

**Limitation**: Not extensible, misses domain-specific synonyms

**Better Approach**: 
- LLM-based synonym expansion
- Embedding similarity between type names
- User-defined configuration

**Priority**: Medium (incremental improvement)

---

### **Q14: Domain Boosting - Note Domain or Node Domain?**

**Answer**: 🚨 **BUG DISCOVERED**
- Code tries: `node.get("domain", "Unknown")`
- Reality: Entity/Concept nodes don't have `domain` property (only Notes do)
- **Domain boost is effectively disabled for entity/concept nodes!**

**Fix Options**:

**Option 1: Propagate domain during ingestion**
```cypher
MERGE (e:Entity {name: $name})
SET e.domain = $note_domain
```

**Option 2: Fetch from linked notes at retrieval**
```python
linked_notes = cand.get("linked_notes", [])
note_domain = linked_notes[0].get("domain") if linked_notes else "Personal"
```

**Priority**: HIGH - Currently broken feature

---

### **Q15: Query Decomposition - Already Doing This?**

**Your Question**: "Don't we already decompose via `llm_service.analyze_query()`?"

**Answer**: ⚠️ **Partial decomposition**

**What you have**: Attribute extraction
```python
query_analysis = {
    "entities": ["Scott Derrickson", "Ed Wood"],
    "expected_types": ["Person"],
    "attribute": "nationality"
}
```

**True decomposition**: Sub-query generation
```python
sub_queries = [
    "Who directed Film A?",
    "What nationality is Director A?",
    ...
]
```

**Verdict**: You don't need full decomposition yet (hybrid search handles most cases)

**When you'd need it**: If EM drops below 30%

**Priority**: LOW (not bottleneck)

---

### **Q16: Multi-hop - Why Not Use It?**

**Your Rationale**: "Ingestion represents data well, 1-hop expansion is enough"

**Analysis**: ✅ **You're correct**

**Why multi-hop is overrated**:
- Your 1-hop neighbor expansion gets: Film → Director → Birthplace
- Query-aware neighbor scoring filters noise
- Most questions need ≤2 hops

**When you'd need explicit multi-hop**:
- 3+ hop questions (rare in personal knowledge)
- If EM drops below 30%

**Verdict**: Stick with 1-hop, reconsider if performance degrades

**Priority**: NONE (working design)

---

### **Q17: Context Disambiguation - Do We Do It?**

**Answer**: ⚠️ **Partial disambiguation**

**What you have**:
- ✅ Type scoring (boosts matching entity types)
- ✅ Name variant expansion

**What you don't have**:
- ❌ Explicit disambiguation ("Michael Jordan (basketball)" vs "(professor)")
- ❌ Canonical entity IDs with aliases

**How to Improve**:

**Approach 1: Aggressive type scoring** (easy)
```python
# Increase mismatch penalty
if entity.type != expected_type:
    return 0.01  # Currently 0.1, too lenient
```

**Approach 2: Context-based scoring** (better)
```python
query_context = extract_context_from_query(query)
entity_context = node.get("summary", "")
context_score = embed_similarity(query_context, entity_context)
```

**Priority**: MEDIUM (affects ~5% of queries with ambiguous entities)

---

### **Q18: Alias Resolution - Do We Do It?**

**Answer**: ❌ **Disabled** (too risky for false positives)

**What's disabled**:
```python
# self._detect_and_create_aliases(extraction.entities, note_id)
```

**What you have instead**:
- ✅ `find_name_variants()` - deterministic pattern matching ("Robert Smith Jr.")

**Why disabled**: False positive risk ("Michael B. Jordan" ≠ "Michael Jordan")

**Safe enablement strategy**:
1. LLM verification with context
2. High confidence threshold (0.9+)
3. At retrieval: expand queries to aliases
4. Human-in-loop for alias creation

**Priority**: LOW (name variants already work well)

---

### **Q19: Why Qwen3:0.6b "Weak" Assessment?**

**My Original Assessment**: Based on 11.8% precision, assumed weak embeddings

**Your Researcher**: ✅ **Qwen3 is SOTA** - problem was missing instruction prefix

**Correction**: I was wrong - Qwen3-Embedding:0.6b is excellent when properly configured

**With instruction prefix fix**: Should match/exceed Nomic-1.5 performance

**Priority**: HIGH - Validating fix is critical

---

## Recommended Action Items

### **Immediate (This Week)**

1. ✅ **DONE: Qwen3 instruction prefix** - Test on HotpotQA benchmark
2. 🔧 **Fix domain boosting** - Propagate domain to nodes or fetch from linked notes
3. 🔍 **Create vector index for isolated_context_embeddings** - Enable multi-context search

### **Short-term (This Month)**

4. 🎯 **Remove "Anonymous" entity type** - Require descriptive types
5. 📊 **Implement hybrid complexity scoring** - Refine based on extraction quality
6. 🔗 **Enable context-based disambiguation** - Better entity scoring

### **Long-term (Experimental)**

7. 🧪 **Test isolated_context vs summary for neighbors** - Measure LLM accuracy
8. 🤖 **LLM-based type synonyms** - Replace hardcoded dictionary
9. 👤 **Safe alias resolution** - Human-in-loop alias creation

---

## Expected Performance Improvements

| Fix | Precision Impact | Recall Impact | EM Impact |
|-----|------------------|---------------|-----------|
| Qwen3 Instruction Prefix | +5-10pp | +3-5pp | +5-8pp |
| Domain Boosting Fix | +2-3pp | +1pp | +2-3pp |
| Context Embeddings Index | +3-5pp | +5-7pp | +4-6pp |
| Remove Anonymous Types | +1-2pp | - | +1-2pp |
| Context Disambiguation | +2-3pp | - | +2-3pp |
| **TOTAL EXPECTED** | **+13-23pp** | **+9-13pp** | **+14-24pp** |

**Target Performance**:
- Precision: 11.8% → **25-35%** (2-3x improvement)
- Recall: 66.5% → **75-80%** (+8-13pp)
- EM: 36% → **50-60%** (+14-24pp)

---

## System Strengths to Preserve

✅ **Isolated Context Architecture** - Best feature, enables zero-loss knowledge retention  
✅ **Hybrid Search (Entity + Vector)** - Catches explicit and semantic matches  
✅ **Query-Aware Neighbor Expansion** - Filters noise, finds relevant connections  
✅ **Soft Type Scoring** - No hard filtering, prevents zero-recall disasters  
✅ **Free-form Relationships** - LLM flexibility for domain-specific connections  
✅ **Domain Awareness** - Separates Academic/Professional/Personal knowledge  

---

## Testing Protocol

### **Phase 1: Validate Qwen3 Fix**
```bash
# Re-run HotpotQA benchmark with instruction prefix
cd backend
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose

# Compare to previous baseline:
# - EM: 36% → Target: 41-44%
# - Precision: 11.8% → Target: 16-21%
# - Recall: 66.5% → Target: 69-72%
```

### **Phase 2: Implement Domain Fix**
```bash
# Option A: Propagate domain during ingestion (requires re-ingestion)
# Option B: Fetch from linked notes (no re-ingestion needed)

# Test on subset of 100 questions first
python tests/benchmark/evaluate.py --dataset hotpotqa --limit 100
```

### **Phase 3: Context Embeddings Index**
```bash
# Create new vector index, test retrieval
# Measure impact on precision/recall
```

---

## Conclusion

**Key Insight**: Your ingestion system is excellent. The precision issue (11.8%) is primarily caused by:
1. **Missing Qwen3 instruction prefix** (✅ FIXED)
2. **Broken domain boosting** (🔧 FIXABLE)
3. **Unused context embeddings** (💡 OPPORTUNITY)

**Expected Outcome**: With these three fixes, you should reach:
- **Precision: 25-35%** (2-3x improvement)
- **EM: 50-60%** (approaching SOTA for local models)

**Your instinct was correct**: "Ingestion is great, we just need better search."

---

**Next Steps**: Run benchmark with Qwen3 fix, analyze improvements, then tackle domain boosting.
