"""
Alias Detection Service - LLM-based node merging with IS_SAME_AS relationships.

Detects when two nodes with different names refer to the same real-world thing
by comparing their contextual summaries using LLM reasoning.

Example: "Elon Musk" vs "Elon" vs "Elon R. Musk" (Entity)
         "AI" vs "Artificial Intelligence" (Concept)
"""

import asyncio
import json
import re
import numpy as np
from typing import Optional
from app.services.graph import graph_service
from app.services.llm import llm_service
from app.services.embedding import embedding_service
from app.core.log import get_logger

logger = get_logger("AliasDetector")


class AliasDetectorService:
    """Detects and links node relationships using LLM-based context analysis.

    The LLM determines the relationship type:
    - IS_SAME_AS: Exact same entity (different names/spellings)
    - IS_VARIANT_OF: Likely same but ambiguous
    - IS_SIMILAR_TO: Different but closely related
    - RELATED_TO: Different but contextually connected
    - NONE: No meaningful relationship
    """

    def __init__(self, max_concurrent_llm_calls: int = 2):
        """Initialize with concurrency limit for LLM calls.

        Args:
            max_concurrent_llm_calls: Max parallel LLM requests (default: 2 for Ollama)
        """
        self.llm_semaphore = asyncio.Semaphore(max_concurrent_llm_calls)

    async def find_potential_aliases(
        self,
        node_value: str,
        node_label: str = "Entity",
        identifier_property: str = "name",
        node_type: Optional[str] = None,
        limit: int = 10000,
        min_semantic_similarity: float = 0.65,
    ) -> list[dict]:
        """
        Find nodes that might be aliases using a two-stage filter:

        Stage 1: Lexical/String Similarity (fast)
        - Levenshtein distance (typos, slight variations)
        - Containment (one name contains the other)
        - Initial matching (J.K. Rowling vs Joanne Rowling)
        - Token overlap (Marie Curie vs Curie, Marie)

        Stage 2: Semantic Similarity Shield (quality gate)
        - Calculate cosine similarity between entity embeddings
        - Filter out candidates with similarity < min_semantic_similarity
        - Prevents garbage like "Brooklyn Theatre" matching "New Orleans Pelicans"

        Args:
            node_value: Value to find aliases for (name/trait/title)
            node_label: Node label (Entity, Concept, Task, Persona, Reference)
            identifier_property: Property name to match on (name, trait, title)
            node_type: Optional type filter (only for Entity: Person, Place, etc)
            limit: Max candidates to return
            min_semantic_similarity: Minimum cosine similarity threshold (0.0-1.0, default 0.65)

        Returns:
            List of semantically similar alias candidates with their summaries
        """
        # Build type filter for Entity nodes only
        type_filter = " AND n.type = $type" if node_type else ""

        # Use APOC for fuzzy string matching
        # Only find candidates that have genuine name similarity
        query = f"""
        MATCH (n:{node_label})
        WHERE n.{identifier_property} <> $value
          {type_filter}
          AND NOT EXISTS {{
            MATCH (source:{node_label} {{{identifier_property}: $value}})
            MATCH (source)-[]-(n)
          }}
          AND (
            // Very close Levenshtein distance (1-2 char difference)
            apoc.text.distance(toLower(n.{identifier_property}), toLower($value)) <= 2
            OR
            // One name fully contains the other (min 4 chars to avoid noise)
            (
              size($value) >= 4 AND size(n.{identifier_property}) >= 4 AND
              (
                toLower(n.{identifier_property}) CONTAINS toLower($value)
                OR toLower($value) CONTAINS toLower(n.{identifier_property})
              )
            )
            OR
            // Multi-word names with same first initial and significant word overlap
            (
              size(split(n.{identifier_property}, ' ')) > 1 
              AND size(split($value, ' ')) > 1
              AND substring(toLower(n.{identifier_property}), 0, 1) = substring(toLower($value), 0, 1)
              AND size([word IN split(toLower(n.{identifier_property}), ' ') WHERE word IN split(toLower($value), ' ') AND size(word) > 2]) >= 1
            )
          )
        RETURN n.{identifier_property} as identifier_value, 
               n.summary as summary,
               n.type as node_type,
               n.facts as facts,
               apoc.text.distance(toLower(n.{identifier_property}), toLower($value)) as distance
        ORDER BY distance ASC
        LIMIT $limit
        """

        params = {
            "value": node_value,
            "limit": limit * 3,
        }  # Get 3x candidates for semantic filtering
        if node_type:
            params["type"] = node_type

        lexical_candidates = graph_service.execute_query(query, params)

        if not lexical_candidates:
            return []

        logger.info(
            f"[Alias] Stage 1 (Lexical): Found {len(lexical_candidates)} candidates for '{node_value}'"
        )

        # SEMANTIC SHIELD: Filter by embedding similarity
        # Get source node embedding
        source_query = f"""
        MATCH (n:{node_label} {{{identifier_property}: $value}})
        RETURN n.embedding as embedding, n.summary as summary
        """

        source_result = graph_service.execute_query(source_query, {"value": node_value})

        if not source_result or not source_result[0].get("embedding"):
            logger.warning(
                f"[Alias] Source node '{node_value}' has no embedding - generating one"
            )
            # Generate embedding from summary
            source_summary = (
                source_result[0].get("summary") if source_result else node_value
            )
            source_embedding = embedding_service.embed_query(
                source_summary or node_value
            )
        else:
            source_embedding = source_result[0]["embedding"]

        # Calculate semantic similarity for each candidate
        semantic_candidates = []
        for candidate in lexical_candidates:
            candidate_name = candidate.get("identifier_value")

            # Get candidate embedding from graph or generate
            candidate_query = f"""
            MATCH (n:{node_label} {{{identifier_property}: $value}})
            RETURN n.embedding as embedding
            """

            candidate_result = graph_service.execute_query(
                candidate_query, {"value": candidate_name}
            )

            if not candidate_result or not candidate_result[0].get("embedding"):
                # Generate embedding if missing
                candidate_summary = candidate.get("summary", candidate_name)
                candidate_embedding = embedding_service.embed_query(candidate_summary)
            else:
                candidate_embedding = candidate_result[0]["embedding"]

            # Calculate cosine similarity
            source_vec = np.array(source_embedding)
            candidate_vec = np.array(candidate_embedding)

            # Normalize vectors
            source_norm = source_vec / (np.linalg.norm(source_vec) + 1e-9)
            candidate_norm = candidate_vec / (np.linalg.norm(candidate_vec) + 1e-9)

            # Cosine similarity
            similarity = float(np.dot(source_norm, candidate_norm))

            # Apply semantic shield
            if similarity >= min_semantic_similarity:
                candidate["semantic_similarity"] = similarity
                semantic_candidates.append(candidate)
            else:
                logger.debug(
                    f"[Alias] Filtered out '{candidate_name}' (similarity: {similarity:.3f} < {min_semantic_similarity})"
                )

        # Sort by semantic similarity (highest first)
        semantic_candidates.sort(
            key=lambda x: x.get("semantic_similarity", 0), reverse=True
        )

        # Limit to requested number
        semantic_candidates = semantic_candidates[:limit]

        logger.info(
            f"[Alias] Stage 2 (Semantic Shield): {len(semantic_candidates)}/{len(lexical_candidates)} candidates passed (threshold: {min_semantic_similarity})"
        )

        if semantic_candidates:
            top_candidates = [
                (c["identifier_value"], c["semantic_similarity"])
                for c in semantic_candidates[:3]
            ]
            logger.debug(f"[Alias] Top candidates: {top_candidates}")

        return semantic_candidates

    async def compare_entities_with_llm(
        self,
        entity1_name: str,
        entity1_context: str,
        entity2_name: str,
        entity2_context: str,
        entity1_facts=None,
        entity2_facts=None,
        use_semaphore: bool = True,
    ) -> tuple[str | None, str]:
        """
        Use LLM to determine relationship type between two entities.

        Args:
            entity1_name: Name of first entity
            entity1_context: Summary/context of first entity
            entity2_name: Name of second entity
            entity2_context: Summary/context of second entity
            entity1_facts: Atomic facts JSON for entity1 (list or JSON string)
            entity2_facts: Atomic facts JSON for entity2 (list or JSON string)
            use_semaphore: Whether to limit concurrency

        Returns:
            (relationship_type, reason)
            - relationship_type: "IS_SAME_AS", "IS_VARIANT_OF", "IS_SIMILAR_TO", "RELATED_TO", or None
            - reason: LLM's explanation
        """

        def _fmt_facts(facts_raw) -> str:
            """Format facts JSON into a readable one-liner for the prompt, or empty string."""
            if not facts_raw:
                return ""
            try:
                facts = (
                    json.loads(facts_raw) if isinstance(facts_raw, str) else facts_raw
                )
                if isinstance(facts, list) and facts:
                    line = "; ".join(
                        f"{f['property']}: {f['value']}"
                        for f in facts
                        if isinstance(f, dict) and f.get("property") and f.get("value")
                    )
                    return f"\nFacts: {line}" if line else ""
            except Exception:
                pass
            return ""

        facts1_str = _fmt_facts(entity1_facts)
        facts2_str = _fmt_facts(entity2_facts)

        prompt = f"""Compare these two entities and determine their relationship.

ENTITY 1: "{entity1_name}"
Context: {entity1_context}{facts1_str}

ENTITY 2: "{entity2_name}"
Context: {entity2_context}{facts2_str}

STEP 1 - List shared facts (ignore name words):
What facts do they share? Consider:
- Are they about the same person/place/thing?
- Do they share biographical details (birth place, dates, roles)?
- Do they share specific events, locations, or relationships?

STEP 2 - Evaluate relationship:
DEFAULT TO NONE. Only assign a relationship when you have clear, concrete evidence.
It is always better to return NONE than to guess. A missed connection is harmless;
a wrong connection corrupts the knowledge graph.

- No shared concrete facts → Relationship: NONE (always prefer this when uncertain)
- Exact same entity, confirmed by matching facts → Relationship: IS_SAME_AS
- Same entity but some facts differ or context is ambiguous → Relationship: IS_VARIANT_OF
- Definitively different but same type/category → Relationship: IS_SIMILAR_TO
- Definitively different but a concrete historical/contextual link exists → Relationship: RELATED_TO
- Any other relationship you can precisely name → use a descriptive UPPER_SNAKE_CASE type
- When in doubt: Relationship: NONE

CRITICAL RULES:
✗ "New York" and "New Orleans" → Both have "New" but are DIFFERENT CITIES → NONE
✗ "Brooklyn Theatre" and "Orleans Pelicans" → Share location words but DIFFERENT TYPES → NONE

✗ "US Navy" and "US Senate" → Both part of US but DIFFERENT BRANCHES → RELATED_TO (not SAME)
✗ "Teen Titans" and "Brooklyn Theatre" → NO CONNECTION despite "new" → NONE

✓ "Elon Musk" and "Elon R. Musk" → Same person, same facts → IS_SAME_AS
✓ "JFK" and "John F. Kennedy" → Same person, abbreviation → IS_SAME_AS
✓ "Ethiopia" and "Eritrea" → Different countries, historical link → RELATED_TO

OUTPUT FORMAT:
Shared Facts: [list 2-3 concrete facts they share, or write "NONE - only share name words"]
Relationship: [choose the most fitting UPPER_SNAKE_CASE relationship type; well-known options: IS_SAME_AS, IS_VARIANT_OF, IS_SIMILAR_TO, RELATED_TO — or propose any descriptive type that better captures the connection (e.g. INSPIRED_BY, PRECURSOR_TO, PART_OF); write NONE if no meaningful relationship exists]
Reason: [One sentence why]

Now analyze the entities above:
"""

        try:
            logger.info(
                f"[Alias] Calling LLM to determine relationship between '{entity1_name}' and '{entity2_name}'"
            )
            logger.debug(f"[Alias] Entity 1 context: {entity1_context[:200]}...")
            logger.debug(f"[Alias] Entity 2 context: {entity2_context[:200]}...")

            # Use semaphore to limit concurrent LLM calls if enabled
            if use_semaphore:
                async with self.llm_semaphore:
                    response = await llm_service.generate(prompt, temperature=0.1)
            else:
                response = await llm_service.generate(prompt, temperature=0.1)
            logger.debug(f"[Alias] Raw LLM response: {response}")

            # Parse response: accept any UPPER_SNAKE_CASE relationship type the LLM proposes.
            # The well-known set (IS_SAME_AS etc.) is offered as suggestions, but the LLM
            # is free to choose a more descriptive type (e.g. INSPIRED_BY, PART_OF).
            relationship_type = None
            reason = "No reason provided"

            lines = response.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("Relationship:"):
                    rel_str = line.replace("Relationship:", "").strip()
                    # Extract the first UPPER_SNAKE_CASE token from the response value
                    candidate_match = re.search(
                        r"\b([A-Z][A-Z0-9_]+[A-Z0-9])\b", rel_str.upper()
                    )
                    if candidate_match:
                        candidate = candidate_match.group(1).strip("_")
                        relationship_type = None if candidate == "NONE" else candidate
                    else:
                        relationship_type = None
                elif line.startswith("Reason:"):
                    reason = line.replace("Reason:", "").strip()

            logger.info(
                f"[Alias] LLM determined relationship '{entity1_name}' ↔ '{entity2_name}': "
                f"{relationship_type or 'NONE'} - {reason}"
            )

            return relationship_type, reason

        except Exception as e:
            logger.error(f"[Alias] LLM comparison failed: {e}")
            return None, f"Error: {e}"

    async def create_relationship_link(
        self,
        entity1_value: str,
        entity2_value: str,
        relationship_type: str,
        node_label: str,
        identifier_property: str,
        reason: str,
    ) -> bool:
        """
        Create a relationship between two entities based on LLM determination.

        Does NOT merge nodes - just creates relationship for retrieval/navigation.
        This is non-destructive and allows manual review/correction later.

        Args:
            entity1_value: First entity identifier value
            entity2_value: Second entity identifier value
            relationship_type: Type of relationship (IS_SAME_AS, IS_VARIANT_OF, IS_SIMILAR_TO, RELATED_TO)
            node_label: Node label (Entity, Concept, etc)
            identifier_property: Property name (name, trait, title)
            reason: LLM's reasoning for the relationship
        """
        # Map relationship type to confidence score
        confidence_map = {
            "IS_SAME_AS": 1.0,  # Certain - exact same entity
            "IS_VARIANT_OF": 0.7,  # Likely same but ambiguous
            "IS_SIMILAR_TO": 0.6,  # Different but closely related
            "RELATED_TO": 0.5,  # Different but connected
        }
        confidence = confidence_map.get(relationship_type, 0.5)

        query = f"""
        MATCH (n1:{node_label} {{{identifier_property}: $entity1_value}})
        MATCH (n2:{node_label} {{{identifier_property}: $entity2_value}})
        
        // Create relationship of appropriate type with standard properties
        CALL apoc.create.relationship(n1, $relationship_type, {{
            reason: $reason,
            detected_at: datetime(),
            method: 'llm_context_analysis',
            is_active: true,
            confidence: $confidence,
            context: $reason
        }}, n2) YIELD rel
        
        RETURN n1.{identifier_property} as entity1, n2.{identifier_property} as entity2, type(rel) as rel_type
        """

        result = graph_service.execute_query(
            query,
            {
                "entity1_value": entity1_value,
                "entity2_value": entity2_value,
                "relationship_type": relationship_type,
                "reason": reason,
                "confidence": confidence,
            },
        )

        if result:
            logger.info(
                f"[Alias] Created {relationship_type} ({node_label}): '{entity1_value}' ↔ '{entity2_value}' | {reason}"
            )
            return True
        else:
            logger.warning(
                f"[Alias] Failed to create {relationship_type} link ({node_label}): {entity1_value} ↔ {entity2_value}"
            )
            return False

    async def detect_and_link_aliases_for_node(
        self,
        node_value: str,
        node_label: str,
        identifier_property: str = "name",
        node_type: Optional[str] = None,
    ) -> list[str]:
        """
        Find and link aliases for a single node.

        Args:
            node_value: Node identifier value to check (name/trait/title)
            node_label: Node label (Entity, Concept, Task, Persona, Reference)
            identifier_property: Property name (name, trait, title)
            node_type: Optional type (only for Entity: Person, Place, etc)

        Returns:
            List of canonical values this node was linked to
        """
        # Build query to get node's context
        type_filter = "type: $type," if node_type else ""
        query = f"""
        MATCH (n:{node_label} {{{type_filter} {identifier_property}: $value}}) 
        RETURN n.summary as summary, n.facts as facts
        """

        params = {"value": node_value}
        if node_type:
            params["type"] = node_type

        node_data = graph_service.execute_query(query, params)

        if not node_data:
            logger.warning(f"[Alias] {node_label} not found: {node_value}")
            return []

        node_summary = node_data[0].get("summary", "")
        node_facts = node_data[0].get("facts")
        if not node_summary or len(node_summary) < 20:
            logger.debug(
                f"[Alias] Skipping '{node_value}' - insufficient context for comparison"
            )
            return []

        # Find potential aliases
        logger.info(
            f"[Alias] Step 1: Searching for fuzzy match candidates for '{node_value}'"
        )
        candidates = await self.find_potential_aliases(
            node_value, node_label, identifier_property, node_type
        )

        if not candidates:
            logger.info(
                f"[Alias] No potential candidates found for '{node_value}' - no fuzzy matches"
            )
            return []

        logger.info(
            f"[Alias] Step 2: Found {len(candidates)} potential candidate(s) for '{node_value}' ({node_label})"
        )
        logger.info(
            f"[Alias] Candidates: {', '.join([c['identifier_value'] for c in candidates])}"
        )

        linked_to = []

        # Compare with each candidate
        for candidate in candidates:
            candidate_value = candidate["identifier_value"]
            candidate_summary = candidate.get("summary", "")
            candidate_facts = candidate.get("facts")
            candidate_similarity = candidate.get("semantic_similarity")

            if not candidate_summary or len(candidate_summary) < 20:
                logger.debug(
                    f"[Alias] Skipping candidate '{candidate_value}' - insufficient context"
                )
                continue

            # LLM determines relationship type
            logger.info(
                f"[Alias] Step 3: Asking LLM to determine relationship between '{node_value}' and '{candidate_value}'"
            )
            print(f"  → Analyzing: {candidate_value}")
            relationship_type, reason = await self.compare_entities_with_llm(
                node_value,
                node_summary,
                candidate_value,
                candidate_summary,
                entity1_facts=node_facts,
                entity2_facts=candidate_facts,
            )
            logger.info(
                f"[Alias] LLM Response: {relationship_type or 'NONE'} | {reason}"
            )

            # Create link if LLM determined a relationship
            if relationship_type:
                logger.info(f"[Alias] Step 4: CREATING {relationship_type} LINK")
                print(f"    ✓ {relationship_type}: {reason}")
                await self.create_relationship_link(
                    entity1_value=node_value,
                    entity2_value=candidate_value,
                    relationship_type=relationship_type,
                    node_label=node_label,
                    identifier_property=identifier_property,
                    reason=reason,
                )
                linked_to.append(f"{candidate_value} ({relationship_type})")
            else:
                logger.info(
                    "[Alias] Step 4: NO RELATIONSHIP - LLM determined no meaningful connection"
                )
                print(f"    - No relationship: {reason}")

        return linked_to


alias_detector = AliasDetectorService()
