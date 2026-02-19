# Potential Future Improvements

This document tracks promising ideas for improving LiveOS Brain performance that require further research, testing, or significant implementation effort.

---

# Potential Future Improvements

This document tracks promising ideas for improving LiveOS Brain performance that require further research, testing, or significant implementation effort.

---

## ACTIVE IMPLEMENTATIONS (Feb 17, 2026)

### ✅ Iterative Information-Discovery Retrieval (ACTIVE)

**Status:** Implemented & Running  
**Expected Impact:** +3-7 F1 by solving complex multi-step questions
**Implementation Time:** 90 minutes

**What It Does:**
1. Ask LLM what information it needs to answer a complex question
2. For each information need:
   - Substitute discovered entities from previous steps
   - Retrieve relevant context (10 docs per step)
   - Extract key entities/facts from results
3. Synthesize final answer with all gathered context

**Example:**
```
Question: "What government position was held by the woman who portrayed Corliss Archer in Kiss and Tell?"

Step 1: "Who portrayed Corliss Archer in the film Kiss and Tell?"
→ Retrieves → Discovers: "Shirley Temple"

Step 2: "What government position did Shirley Temple hold?"
→ Retrieves with filled entity → Discovers: "Chief of Protocol"

Final: Synthesizes answer with all context
```

**Why It Works:**
- LLM dynamically determines information needs (no hardcoded patterns)
- Each step is targeted and specific
- Handles questions where intermediate entities aren't mentioned in original query
- Simpler than previous decomposition attempt (no complex sub-question generation)

**Files Modified:**
- `app/services/llm.py`: Added `identify_information_needs()` and `extract_discovered_entities()`
- `app/workflows/chat.py`: Completely rewritten to use iterative retrieval

**Difference from Multi-Hop:**
- **Multi-hop**: Follow existing graph connections (A → B → C via relationships)
- **Multi-step**: Identify intermediate entity, then search FOR that entity's attributes
- Example: Finding Shirley Temple requires discovering her name first, then searching for her specifically

---

### ✅ Removed Isolated Context from Retrieval (COMPLETED)

**Status:** Removed  
**Expected Impact:** Simplified code, faster retrieval, no accuracy loss
**Implementation Time:** 15 minutes

**What Changed:**
- `USE_ISOLATED_CONTEXTS = False` (was True)
- Retrieval now uses LLM summaries only (not isolated contexts)
- Removed context-level filtering logic
- Removed query embedding storage for filtering

**Why Removed:**
- Summaries are comprehensive enough (observed in retrieval tests)
- Every retrieved node summary was clear and complete
- Context-level filtering added complexity without clear benefit
- Reduces embedding storage and retrieval overhead

**What We Keep:**
- ✅ Still generate isolated contexts during ingestion (for summary quality)
- ✅ Still use them to build comprehensive summaries
- ❌ No longer retrieve/filter isolated contexts during search

---

### ✅ Relationship-Aware Retrieval (ACTIVE)

**Status:** Implemented & Running  
**Expected Impact:** +2-4 F1 by providing natural language connection context
**Implementation Time:** 30 minutes

**What It Does:**
- Fetches 1-hop relationships for matched entities
- Sends natural language context to LLM (e.g., "Edward Wood directed Ed Wood")
- Helps with multi-hop questions by making connections explicit

**Example Output:**
```
[Consensus - Person: Edward Wood] | Connections: Edward Wood directed Ed Wood; Edward Wood wrote Plan 9 from Outer Space
```

**Why It Works:**
- Existing neighbor expansion already finds related nodes
- Adding natural language relationship descriptions helps LLM understand connections
- No additional retrieval overhead - relationships loaded once

**Files Modified:**
- `app/services/retrieval.py`: Added `_get_node_relationships()` method
- Format: Prioritizes `context` field (natural language) over technical rel types

---

### ✅ Improved Vector Search Precision (ACTIVE)

**Status:** Implemented & Running  
**Expected Impact:** +0.5-1 F1 by reducing retrieval noise
**Implementation Time:** 5 minutes

**What Changed:**
- Min score threshold: 0.68 → 0.7
- Applied to both vector search and candidate filtering
- Reduces weak matches from qwen3-embedding:0.6b

**Trade-off:**
- Slightly lower recall (fewer weak matches)
- Higher precision (stronger semantic matches only)
- Net positive for answer quality

---

### ❌ Multi-Hop Query Decomposition (REMOVED)

**Status:** Implemented then removed  
**Reason:** Existing neighbor expansion already handles multi-hop queries effectively

**Why Removed:**
1. Neighbor expansion in retrieval already follows relationship chains
2. Added unnecessary complexity and failure modes (missing MODEL_SYNTHESIS setting)
3. Would 2-3x increase latency without clear benefit
4. Baseline system (13.65% F1) works well with simpler architecture

**Lessons Learned:**
- Don't over-engineer - use existing graph traversal capabilities
- Simpler is better when existing solution works
- Multi-hop reasoning can be handled at retrieval level, not decomposition level

---

## EXPECTED PERFORMANCE

**Baseline (before today):**
- 13.65% F1 on HotpotQA
- 15.3s avg response time

**Current Target (with active implementations):**
- 17-22% F1 on HotpotQA (+3.5-8.5 points)
  - Information-discovery retrieval: +3-7 points (solving previously impossible questions)
  - Relationship context: +0.5-1 points (explicit connections)
  - Vector precision: +0.5-1 points (reduced noise)
- 18-25s avg response time (iterative retrieval adds 2-4 steps per question)

**Expected Question Types Improvement:**
- **Multi-step questions** (biggest gain): Previously failed, now solvable
  - Example: "What position was held by the woman who portrayed Corliss Archer?"
  - Baseline: 0-5% accuracy → Target: 40-60%
- **Comparison questions**: Slight improvement from relationship context
  - Baseline: 20-30% → Target: 25-35%
- **Single-hop questions**: Minimal change
  - Baseline: 15-20% → Target: 16-21%

**Test Commands:**
```bash
# Full evaluation
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose

# Quick test (5 questions)
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose --limit 5

# Test information discovery
python test_information_discovery.py
```

---

## 1. Question Decomposition for Multi-Hop Reasoning

**Status:** ❌ REMOVED (Feb 17, 2026) - Existing neighbor expansion is sufficient

Current system struggles with multi-hop reasoning questions that require:
- Comparing attributes across multiple entities ("Were X and Y of the same nationality?")
- Chaining information from multiple sources ("Who held a position at the organization founded by X?")
- Synthesizing facts from disconnected contexts

**Current Performance:**
- Comparison questions: ~10% F1
- Multi-hop questions: ~12% F1
- Overall: 13.35% F1 on HotPotQA

**Root Cause:** The 4B parameter LLM (gemma3:4b) struggles to synthesize complex reasoning from retrieved context, even when relevant information is present.

### Option A: LLM-Driven Question Decomposition Agent

**Approach:** Use LLM to break complex questions into simple sub-questions, answer each independently, then synthesize.

**Architecture:**
```python
async def answer_with_decomposition(question: str):
    """
    Multi-step reasoning with explicit decomposition.
    
    Example:
        Question: "Were Scott Derrickson and Ed Wood of the same nationality?"
        
        Step 1: Decompose
            → ["Who is Scott Derrickson?",
               "What is Scott Derrickson's nationality?",
               "Who is Ed Wood?",
               "What is Ed Wood's nationality?"]
        
        Step 2: Answer sub-questions
            → ["American filmmaker", "American", "American filmmaker", "American"]
        
        Step 3: Synthesize
            → "Yes, both are American"
    """
    
    # Step 1: LLM decomposes question
    decomposition = await llm_service.decompose_question(question)
    
    # Returns structured plan:
    # {
    #     "question_type": "comparison",
    #     "entities": ["Scott Derrickson", "Ed Wood"],
    #     "attribute": "nationality",
    #     "sub_questions": [
    #         {"text": "What is Scott Derrickson's nationality?", "type": "attribute"},
    #         {"text": "What is Ed Wood's nationality?", "type": "attribute"}
    #     ],
    #     "synthesis_template": "Compare the nationalities and return 'yes' if same, 'no' if different"
    # }
    
    # Step 2: Answer each sub-question independently
    sub_answers = []
    for sub_q in decomposition['sub_questions']:
        # Each sub-question gets fresh retrieval
        sub_answer = await retrieval_service.hybrid_search(sub_q['text'])
        answer_text = await llm_service.generate_answer(sub_q['text'], sub_answer)
        sub_answers.append({
            "question": sub_q['text'],
            "answer": answer_text
        })
    
    # Step 3: Synthesize final answer
    final_answer = await llm_service.synthesize_from_sub_answers(
        original_question=question,
        sub_answers=sub_answers,
        synthesis_template=decomposition['synthesis_template']
    )
    
    return final_answer
```

**Prompt Template for Decomposition:**
```python
DECOMPOSE_PROMPT = """
You are a question decomposition expert. Break down complex questions into simple sub-questions.

Question: {question}

Analyze the question and return:
1. Question type (comparison, multi_hop, attribute_lookup, counting, etc.)
2. Main entities mentioned
3. Attribute or relationship being queried
4. List of sub-questions that, when answered, provide all information needed
5. A synthesis template explaining how to combine sub-answers

Return JSON:
{{
    "question_type": "comparison|multi_hop|attribute|counting|other",
    "entities": ["entity1", "entity2", ...],
    "attribute": "nationality|birthdate|occupation|etc",
    "sub_questions": [
        {{"text": "sub-question 1", "type": "entity_lookup|attribute|relationship"}},
        ...
    ],
    "synthesis_template": "Instructions for combining answers"
}}

Examples:

Input: "Were Scott Derrickson and Ed Wood of the same nationality?"
Output:
{{
    "question_type": "comparison",
    "entities": ["Scott Derrickson", "Ed Wood"],
    "attribute": "nationality",
    "sub_questions": [
        {{"text": "What is Scott Derrickson's nationality?", "type": "attribute"}},
        {{"text": "What is Ed Wood's nationality?", "type": "attribute"}}
    ],
    "synthesis_template": "Compare nationalities. Return 'yes' if identical, 'no' otherwise."
}}

Input: "What government position was held by the woman who portrayed Corliss Archer in Kiss and Tell?"
Output:
{{
    "question_type": "multi_hop",
    "entities": ["Corliss Archer", "Kiss and Tell"],
    "attribute": "occupation",
    "sub_questions": [
        {{"text": "Who portrayed Corliss Archer in Kiss and Tell?", "type": "relationship"}},
        {{"text": "What government position did [actress name] hold?", "type": "attribute"}}
    ],
    "synthesis_template": "Extract the actress name from first answer, then return the government position from second answer."
}}
"""
```

**Advantages:**
- ✅ Works for any question type (flexible)
- ✅ Explicit reasoning chain (debuggable)
- ✅ Can handle complex natural language
- ✅ Leverages LLM's planning abilities

**Disadvantages:**
- ⚠️ 2-5x slower (multiple LLM calls + multiple retrievals)
- ⚠️ Requires good decomposition prompt engineering
- ⚠️ May over-complicate simple questions
- ⚠️ Decomposition quality depends on LLM capability (gemma3:4b may struggle)

**Expected Performance:**
- Comparison questions: 10% → 40-50% F1 (+30-40 points)
- Multi-hop questions: 12% → 25-30% F1 (+13-18 points)
- Overall: 13.35% → 18-20% F1 (+5-7 points)
- Response time: 22s → 45-90s (2-4x slower)

---

### Option B: Structured Attribute-Based Retrieval

**Approach:** For structured questions (comparisons, attribute lookups), bypass LLM reasoning and use direct graph queries.

**Architecture:**
```python
async def answer_with_structured_retrieval(question: str):
    """
    Fast, accurate answering for structured questions using graph queries.
    
    Example:
        Question: "Were Scott Derrickson and Ed Wood of the same nationality?"
        
        Step 1: Parse question structure
            → Type: comparison
            → Entities: ["Scott Derrickson", "Ed Wood"]
            → Attribute: nationality
        
        Step 2: Direct graph query
            → MATCH (e1:Entity {name: "Scott Derrickson"})
            → MATCH (e2:Entity {name: "Ed Wood"})
            → RETURN e1.nationality, e2.nationality
        
        Step 3: Compare programmatically
            → "American" == "American" → "Yes"
    """
    
    # Step 1: Classify question and extract structure
    structure = await parse_question_structure(question)
    
    # Returns:
    # {
    #     "type": "comparison",
    #     "entities": ["Scott Derrickson", "Ed Wood"],
    #     "attribute": "nationality",
    #     "operation": "equality"
    # }
    
    if structure['type'] == 'comparison':
        return await handle_comparison_question(structure)
    elif structure['type'] == 'attribute_lookup':
        return await handle_attribute_question(structure)
    elif structure['type'] == 'multi_hop':
        return await handle_multi_hop_question(structure)
    else:
        # Fall back to regular retrieval for unstructured questions
        return await answer_with_regular_retrieval(question)


async def handle_comparison_question(structure: dict):
    """
    Handle questions like "Are X and Y both Z?" or "Were X and Y of the same Z?"
    """
    entities = structure['entities']
    attribute = structure['attribute']
    
    # Direct graph query to get attribute values
    query = """
    UNWIND $entity_names as entity_name
    MATCH (e:Entity {name: entity_name})
    RETURN e.name as name, e[$attribute] as value
    """
    
    results = graph_service.execute_query(query, {
        "entity_names": entities,
        "attribute": attribute
    })
    
    # Extract values
    values = [r['value'] for r in results if r['value']]
    
    if len(values) != len(entities):
        # Some entities missing attribute - fall back to semantic search
        return await fallback_to_semantic_retrieval(structure)
    
    # Compare values programmatically
    if structure['operation'] == 'equality':
        all_same = len(set(values)) == 1
        return "yes" if all_same else "no"
    elif structure['operation'] == 'both_true':
        return "yes" if all(values) else "no"
    else:
        return await fallback_to_semantic_retrieval(structure)


async def handle_attribute_question(structure: dict):
    """
    Handle questions like "What is X's Y?" or "When was X born?"
    """
    entity = structure['entity']
    attribute = structure['attribute']
    
    # Direct property lookup
    query = """
    MATCH (e:Entity {name: $entity_name})
    RETURN e[$attribute] as value
    """
    
    result = graph_service.execute_query(query, {
        "entity_name": entity,
        "attribute": attribute
    })
    
    if result and result[0]['value']:
        return result[0]['value']
    else:
        # Attribute not stored - fall back to semantic search
        return await fallback_to_semantic_retrieval(structure)


async def handle_multi_hop_question(structure: dict):
    """
    Handle questions requiring relationship traversal.
    
    Example: "What position was held by the woman who portrayed Corliss Archer?"
    → Step 1: Find actress who portrayed Corliss Archer
    → Step 2: Get her government position
    """
    
    # Parse relationship chain
    steps = structure['relationship_chain']
    
    # Example steps:
    # [
    #     {"type": "portrayed_by", "source": "Corliss Archer", "target": "?"},
    #     {"type": "held_position", "source": "?", "target": "ANSWER"}
    # ]
    
    current_entity = steps[0]['source']
    
    for step in steps:
        if step['type'] == 'portrayed_by':
            # Graph query: MATCH (role)-[:PORTRAYED_BY]->(actor)
            query = """
            MATCH (role:Entity {name: $name})-[:PORTRAYED_BY]->(actor:Person)
            RETURN actor.name as name
            """
            result = graph_service.execute_query(query, {"name": current_entity})
            current_entity = result[0]['name'] if result else None
        
        elif step['type'] == 'held_position':
            # Graph query: Get occupation/government_position attribute
            query = """
            MATCH (person:Person {name: $name})
            RETURN person.government_position as position, person.occupation as occupation
            """
            result = graph_service.execute_query(query, {"name": current_entity})
            if result:
                return result[0]['position'] or result[0]['occupation']
        
        if not current_entity:
            # Relationship not found - fall back
            return await fallback_to_semantic_retrieval(structure)
    
    return None
```

**Structured Fact Extraction During Ingestion:**

To support this approach, we need to extract structured facts during ingestion:

```python
# In ingestion workflow, after entity extraction:
async def extract_structured_facts(entity: Entity, context: str):
    """
    Extract structured attributes for direct querying.
    
    Example:
        Entity: "Ed Wood"
        Context: "Edward D. Wood Jr. was an American filmmaker born October 10, 1924."
        
        Extracted Facts:
        {
            "name": "Ed Wood",
            "nationality": "American",
            "occupation": "filmmaker",
            "birth_date": "1924-10-10",
            "full_name": "Edward D. Wood Jr."
        }
    """
    
    prompt = f"""
    Extract structured facts about {entity.name} ({entity.type}) from the context.
    
    Context: {context}
    
    Return JSON with available attributes:
    {{
        "nationality": "...",
        "occupation": "...",
        "birth_date": "YYYY-MM-DD",
        "death_date": "YYYY-MM-DD",
        "birth_place": "...",
        "education": "...",
        "spouse": "...",
        "government_position": "..."
    }}
    
    Only include attributes explicitly mentioned. Use null for missing attributes.
    """
    
    facts = await llm_service.extract_structured_facts(prompt)
    
    # Store as node properties
    graph_service.update_entity_properties(entity.name, facts)
```

**Advantages:**
- ✅ Extremely fast (direct graph queries, no LLM needed)
- ✅ High precision on structured questions (90%+ accuracy)
- ✅ Deterministic (no LLM hallucination)
- ✅ Explainable (query path is clear)

**Disadvantages:**
- ⚠️ Only works for structured questions (~40% of HotPotQA)
- ⚠️ Requires fact extraction during ingestion (slower ingestion)
- ⚠️ Brittle (fails if attribute not extracted)
- ⚠️ Doesn't handle complex natural language
- ⚠️ High maintenance (need to define attribute schemas)

**Expected Performance:**
- Comparison questions: 10% → 85-90% F1 (+75-80 points)
- Attribute questions: 20% → 80-85% F1 (+60-65 points)
- Multi-hop (structured): 12% → 40-50% F1 (+28-38 points)
- Overall: 13.35% → 20-25% F1 (+7-12 points, but only 40% coverage)
- Response time: 22s → 5-8s for structured, 22s for unstructured

---

## 2. Hybrid Approach (Recommended)

**Strategy:** Combine both options for best results.

```python
async def answer_question(question: str):
    """
    Smart routing based on question type.
    """
    
    # Step 1: Classify question
    classification = await classify_question(question)
    
    # Step 2: Route to appropriate handler
    if classification['is_structured'] and classification['confidence'] > 0.8:
        # Use Option B: Fast structured retrieval
        try:
            answer = await answer_with_structured_retrieval(question)
            if answer:  # Success
                return answer
        except Exception as e:
            logger.warning(f"Structured retrieval failed: {e}")
    
    # Step 3: Fall back to decomposition for complex questions
    if classification['requires_multi_hop'] or classification['question_type'] == 'comparison':
        return await answer_with_decomposition(question)
    
    # Step 4: Fall back to regular retrieval for simple questions
    return await answer_with_regular_retrieval(question)
```

**Expected Performance:**
- Comparison questions: 10% → 70-80% F1 (structured: 85%, decomposition: 40%)
- Multi-hop questions: 12% → 35-40% F1
- Overall: 13.35% → 22-28% F1 (+9-15 points)
- Response time: Average 20s (structured: 5s, decomposition: 50s, regular: 22s)

---

## Implementation Roadmap

### Phase 1: Structured Retrieval (2 days)
1. Add fact extraction to ingestion workflow
2. Implement comparison question handler
3. Implement attribute question handler
4. Test on comparison questions subset (20 questions)

### Phase 2: Question Decomposition (3 days)
1. Implement decomposition prompt
2. Build sub-question answering pipeline
3. Implement synthesis logic
4. Test on multi-hop questions subset (20 questions)

### Phase 3: Hybrid System (1 day)
1. Build question classifier
2. Implement routing logic
3. Add fallback mechanisms

### Phase 4: Evaluation (1 day)
1. Run full HotPotQA evaluation (100 questions)
2. Compare with baseline (13.35% F1)
3. Analyze performance by question type
4. Measure timing impact

**Total Effort:** 7 days  
**Expected ROI:** +9-15 F1 points (13% → 22-28%)

---

## Alternatives Considered

### Option C: Larger LLM
- **Approach:** Upgrade from gemma3:4b to Llama3-70B or GPT-4
- **Pros:** Likely +10-20 F1 points with no architecture changes
- **Cons:** 17x more expensive, 10x slower, requires cloud/larger hardware
- **Verdict:** Revisit after exhausting 4B model optimizations

### Option D: Fine-tuning
- **Approach:** Fine-tune gemma3:4b on HotPotQA training set
- **Pros:** Tailored to multi-hop reasoning
- **Cons:** Requires GPU, training data, may overfit
- **Verdict:** Consider after Phase 4 if F1 < 25%

### Option E: Chain-of-Thought Prompting
- **Approach:** Add "Let's think step by step" to prompts
- **Pros:** Easy to implement (1 hour)
- **Cons:** Limited impact with small models (~+1-2 F1 points)
- **Verdict:** Already implicitly included in current prompts

---

## RECENT IMPLEMENTATIONS (Feb 17, 2026)

### 1. Multi-Hop Query Decomposition ✅
- **Status:** Implemented, pending evaluation
- **Expected Impact:** +5-8 F1 on HotpotQA
- **Details:** See Section 1 above

### 2. Relationship-Aware Retrieval ✅
- **Status:** Implemented, pending evaluation
- **Expected Impact:** +2-4 F1 by providing connection context
- **Implementation:**
  - Added `_get_node_relationships()` method in retrieval service
  - Fetches 1-hop neighbors for entity and vector matches
  - Formats: `[Entity] | Connections: RELATIONSHIP → Connected Entity`
  - Provides explicit relationship paths for multi-hop reasoning
- **Files Modified:**
  - `app/services/retrieval.py`: Added relationship fetching and formatting

### 3. Improved Vector Search Precision ✅
- **Status:** Implemented, pending evaluation
- **Expected Impact:** +0.5-1 F1 by reducing noise
- **Implementation:**
  - Increased min_score threshold: 0.68 → 0.7
  - Applied to both vector search and candidate filtering
  - Reduces weak semantic matches from qwen3-embedding:0.6b
- **Files Modified:**
  - `app/services/retrieval.py`: Updated thresholds in 2 locations

### Combined Expected Impact
- **Baseline:** 13.65% F1 (hybrid approach with isolated contexts)
- **Target:** 18-22% F1 with all three improvements
- **Breakdown:**
  - Multi-hop decomposition: +5-8 points
  - Relationship-aware retrieval: +2-4 points
  - Vector search precision: +0.5-1 points

### Next Evaluation
```bash
# Run full evaluation to measure combined impact
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose

# Compare results with baseline:
# - Baseline: 13.65% F1, 15.3s avg response time
# - Target: 18-22% F1
# - Trade-off: Decomposition will increase latency (2-3x slower)
```

---

## Next Steps

1. **Priority 1:** ~~Run backfill script to add isolated context embeddings~~ ✅ COMPLETED
   - 6,365 nodes processed with isolated context embeddings
   - Hybrid approach implemented (summary search + context generation)

2. **Priority 2:** Re-evaluate with all improvements ⏳ IN PROGRESS
   ```bash
   python scripts/backfill_isolated_context_embeddings.py --dry-run
   python scripts/backfill_isolated_context_embeddings.py
   ```
   
   **How it works:**
   - Each isolated context gets its own embedding (no averaging)
   - Embeddings stored as JSON string (Neo4j limitation: can't store nested arrays)
   - During search: Parse JSON, compute cosine similarity in Python for each context
   - Only the specific contexts that match the query are returned to the LLM
   - This provides precise, context-specific retrieval vs. entity-level summaries
   
   **Technical Notes:**
   - Property: `isolated_context_embeddings_json` (JSON string of embedding arrays)
   - Property: `isolated_context_count` (integer count for quick filtering)
   - Search happens in Python (fetch nodes → parse JSON → compute similarity)
   - Trade-off: Slightly slower than native Neo4j vector search, but enables per-context matching

2. **Priority 2:** Re-evaluate with isolated context embeddings
   ```bash
   python tests/benchmark/evaluate.py --dataset hotpotqa --verbose
   ```
   
   **Expected improvement:**
   - Better retrieval precision (return only relevant contexts, not all contexts for an entity)
   - More focused generation (LLM sees only the contexts that matched, not irrelevant ones)
   - Potential +3-5 F1 points from improved context quality

4. **Priority 4:** If Phase 1 successful (F1 +5-10 points on subset), implement Phase 2 (Decomposition)

---

**Document Version:** 1.0  
**Last Updated:** February 17, 2026  
**Author:** LiveOS Brain Development Team
