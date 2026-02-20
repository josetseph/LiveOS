"""
Alias Detection Service - LLM-based node merging with IS_SAME_AS relationships.

Detects when two nodes with different names refer to the same real-world thing
by comparing their contextual summaries using LLM reasoning.

Example: "Elon Musk" vs "Elon" vs "Elon R. Musk" (Entity)
         "AI" vs "Artificial Intelligence" (Concept)
"""

import asyncio
from typing import Optional
from app.services.graph import graph_service
from app.services.llm import llm_service
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

    def __init__(self):
        pass  # No configuration needed - LLM makes all decisions

    async def find_potential_aliases(
        self,
        node_value: str,
        node_label: str = "Entity",
        identifier_property: str = "name",
        node_type: Optional[str] = None,
        limit: int = 10000,
    ) -> list[dict]:
        """
        Find nodes that might be aliases based on string similarity.

        Uses multiple fuzzy matching strategies:
        1. Levenshtein distance (typos, slight variations)
        2. Containment (one name contains the other)
        3. Initial matching (J.K. Rowling vs Joanne Rowling)
        4. Token overlap (Marie Curie vs Curie, Marie)

        Args:
            node_value: Value to find aliases for (name/trait/title)
            node_label: Node label (Entity, Concept, Task, Persona, Reference)
            identifier_property: Property name to match on (name, trait, title)
            node_type: Optional type filter (only for Entity: Person, Place, etc)
            limit: Max candidates to return

        Returns:
            List of potential alias candidates with their summaries
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
               n.isolated_contexts as contexts,
               apoc.text.distance(toLower(n.{identifier_property}), toLower($value)) as distance
        ORDER BY distance ASC
        LIMIT $limit
        """

        params = {"value": node_value, "limit": limit}
        if node_type:
            params["type"] = node_type

        results = graph_service.execute_query(query, params)

        return results

    async def compare_entities_with_llm(
        self,
        entity1_name: str,
        entity1_context: str,
        entity2_name: str,
        entity2_context: str,
    ) -> tuple[str | None, str]:
        """
        Use LLM to determine relationship type between two entities.

        Args:
            entity1_name: Name of first entity
            entity1_context: Summary/context of first entity
            entity2_name: Name of second entity
            entity2_context: Summary/context of second entity

        Returns:
            (relationship_type, reason)
            - relationship_type: "IS_SAME_AS", "IS_VARIANT_OF", "IS_SIMILAR_TO", "RELATED_TO", or None
            - reason: LLM's explanation
        """
        prompt = f"""Analyze the relationship between these two entities based on their names and contexts.

ENTITY 1: "{entity1_name}"
Context: {entity1_context[:800]}

ENTITY 2: "{entity2_name}"
Context: {entity2_context[:800]}

# RELATIONSHIP TYPES

Determine which relationship best describes how these entities are connected:

**IS_SAME_AS** - They are THE EXACT SAME entity (just different names/spellings)
- "Elon Musk" ↔ "Elon R. Musk" (same person, full name vs short name)
- "JFK" ↔ "John F. Kennedy" (same person, abbreviation vs full name)
- "New York City" ↔ "NYC" (same place, abbreviation)
- "Dr. Smith" ↔ "John Smith" (same person, title variation)

**IS_VARIANT_OF** - Likely the same but ambiguous/uncertain
- "Apple" ↔ "Apple Inc" (context needed - company vs fruit?)
- "Michael Jordan" ↔ "M. Jordan" (which Michael Jordan?)
- "Paris" ↔ "Paris, France" (vs Paris, Texas?)
- Not enough context to be certain they're the same

**IS_SIMILAR_TO** - Different entities but closely related/analogous
- "violin" ↔ "viola" (different instruments, same family)
- "iPhone 14" ↔ "iPhone 15" (different models, same product line)
- "Harvard" ↔ "MIT" (different universities, both in Boston)
- "Python" ↔ "JavaScript" (different programming languages)

**RELATED_TO** - Different entities with contextual connection
- "Ethiopia" ↔ "Eritrea" (neighboring countries, historical connection)
- "Steve Jobs" ↔ "Apple Inc" (person founded company)
- "World War II" ↔ "D-Day" (event within larger event)
- "piano" ↔ "Mozart" (composer known for instrument)

**NONE** - No meaningful relationship
- "basketball" ↔ "quantum physics" (completely unrelated)
- "cat" ↔ "car" (similar names but totally different)
- Insufficient context to determine any relationship

# DECISION RULES

1. **IS_SAME_AS**: Only if they're LITERALLY the exact same person/place/thing
   - Same biographical facts, just different name forms
   - One is abbreviation/nickname/title of the other
   - Zero doubt they're identical

2. **IS_VARIANT_OF**: Probably same but not certain
   - Names suggest same entity but contexts don't confirm
   - Ambiguous which specific instance is meant
   - Need more info to be sure

3. **IS_SIMILAR_TO**: Definitely different but analogous
   - Same category/type but distinct instances
   - Related by being similar, not by being the same
   - "Same kind of thing" not "same thing"

4. **RELATED_TO**: Different but contextually connected
   - Connected through history, geography, relationships
   - One caused/influenced/involved the other
   - Meaningful connection but clearly different entities

5. **NONE**: When unsure or no relationship
   - Completely unrelated
   - Not enough information
   - When in doubt, choose NONE

# COMMON MISTAKES TO AVOID

❌ DON'T use IS_SAME_AS for:
- Generic → Specific ("company" → "Microsoft")
- Category → Member ("instrument" → "guitar")
- Similar but distinct ("violin" → "viola")
- Related geographically ("Ethiopia" → "Eritrea")
- Same family/type ("iPhone 14" → "iPhone 15")

✅ DO use IS_SAME_AS only when:
- Literally the exact same entity
- Just different name forms
- Zero ambiguity

# OUTPUT FORMAT

Relationship: [IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO|NONE]
Reason: [One sentence explanation]

# EXAMPLES

ENTITY 1: "Elon Musk"
Context: CEO of Tesla and SpaceX, founded in 2002. Born in South Africa, moved to US.

ENTITY 2: "Elon R. Musk"
Context: Founder of SpaceX and Tesla, entrepreneur known for electric vehicles.

Relationship: IS_SAME_AS
Reason: Same person - all biographical facts match, just different name forms.

---

ENTITY 1: "Ethiopia"
Context: Country in East Africa, capital is Addis Ababa, historical kingdom.

ENTITY 2: "Eritrea"
Context: Country in East Africa, gained independence from Ethiopia in 1993.

Relationship: RELATED_TO
Reason: Different countries with historical connection - Eritrea was part of Ethiopia until 1993.

---

ENTITY 1: "violin"
Context: String instrument played with a bow, has four strings, used in orchestras.

ENTITY 2: "viola"
Context: String instrument larger than violin, slightly lower pitch, also played with bow.

Relationship: IS_SIMILAR_TO
Reason: Different instruments from the same family with similar construction but distinct sizes and ranges.

---

ENTITY 1: "Apple"
Context: A company that makes consumer electronics.

ENTITY 2: "Apple Inc"
Context: Technology company headquartered in Cupertino.

Relationship: IS_SAME_AS
Reason: Same company - contexts both describe the technology company, same entity.

---

ENTITY 1: "Michael Jordan"
Context: NBA basketball player, Chicago Bulls.

ENTITY 2: "M. Jordan"
Context: Researcher in computer science.

Relationship: NONE
Reason: Insufficient information - could be different people with same surname, contexts describe different professions.

---

Now analyze the entities above:
"""

        try:
            logger.info(
                f"[Alias] Calling LLM to determine relationship between '{entity1_name}' and '{entity2_name}'"
            )
            logger.debug(f"[Alias] Entity 1 context: {entity1_context[:200]}...")
            logger.debug(f"[Alias] Entity 2 context: {entity2_context[:200]}...")

            response = await llm_service.generate(prompt, temperature=0.1)
            logger.debug(f"[Alias] Raw LLM response: {response}")

            # Parse response
            relationship_type = None
            reason = "No reason provided"

            lines = response.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("Relationship:"):
                    rel_str = line.replace("Relationship:", "").strip().upper()
                    # Map to valid relationship types
                    if "IS_SAME_AS" in rel_str or "SAME_AS" in rel_str:
                        relationship_type = "IS_SAME_AS"
                    elif "IS_VARIANT_OF" in rel_str or "VARIANT_OF" in rel_str:
                        relationship_type = "IS_VARIANT_OF"
                    elif "IS_SIMILAR_TO" in rel_str or "SIMILAR_TO" in rel_str:
                        relationship_type = "IS_SIMILAR_TO"
                    elif "RELATED_TO" in rel_str:
                        relationship_type = "RELATED_TO"
                    elif "NONE" in rel_str:
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
        query = f"""
        MATCH (n1:{node_label} {{{identifier_property}: $entity1_value}})
        MATCH (n2:{node_label} {{{identifier_property}: $entity2_value}})
        
        // Create relationship of appropriate type
        CALL apoc.create.relationship(n1, $relationship_type, {{
            reason: $reason,
            detected_at: datetime(),
            method: 'llm_context_analysis'
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
        RETURN n.summary as summary, n.isolated_contexts as contexts
        """

        params = {"value": node_value}
        if node_type:
            params["type"] = node_type

        node_data = graph_service.execute_query(query, params)

        if not node_data:
            logger.warning(f"[Alias] {node_label} not found: {node_value}")
            return []

        node_summary = node_data[0].get("summary", "")
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
                node_value, node_summary, candidate_value, candidate_summary
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

    # Backward compatibility wrapper for Entity nodes
    async def detect_and_link_aliases_for_entity(
        self, entity_name: str, entity_type: str
    ) -> list[str]:
        """Backward compatibility wrapper for Entity nodes."""
        return await self.detect_and_link_aliases_for_node(
            node_value=entity_name,
            node_label="Entity",
            identifier_property="name",
            node_type=entity_type,
        )

    async def batch_detect_aliases(
        self, entity_type: Optional[str] = None, limit: int = 100
    ) -> dict:
        """
        Run alias detection on all entities (or specific type).

        This is the main batch job function.

        Args:
            entity_type: Optional - only process this entity type (e.g., "Person")
            limit: Max entities to process in this batch

        Returns:
            Statistics dict with counts
        """
        logger.info(
            f"[Alias] Starting batch alias detection (type={entity_type}, limit={limit})"
        )

        # Get entities without existing IS_SAME_AS links (not already aliases)
        type_filter = f"{{type: '{entity_type}'}}" if entity_type else ""
        query = f"""
        MATCH (e:Entity {type_filter})
        WHERE NOT (e)-[:IS_SAME_AS]->()
          AND e.summary IS NOT NULL
          AND size(e.summary) > 20
        RETURN e.name as name, e.type as type
        LIMIT $limit
        """

        entities = graph_service.execute_query(query, {"limit": limit})

        total_entities = len(entities)
        logger.info("[Alias] ===== BATCH DETECTION STARTED =====")
        logger.info(
            f"[Alias] Processing {total_entities} entities | LLM will determine relationship types"
        )
        print(
            f"\n[Progress] Starting relationship detection for {total_entities} entities...\n"
        )

        stats = {
            "processed": 0,
            "links_created": 0,
            "no_candidates": 0,
            "insufficient_context": 0,
        }

        for idx, entity in enumerate(entities, 1):
            entity_name = entity["name"]
            entity_type_value = entity["type"]

            # Type guard: skip if entity_type is None
            if not entity_type_value:
                logger.warning(f"[Alias] Skipping '{entity_name}' - no entity_type")
                continue

            # Show progress for current entity
            logger.info(
                f"[Alias] ===== [{idx}/{total_entities}] Processing entity: '{entity_name}' (type: {entity_type_value}) ====="
            )
            print(
                f"[{idx}/{total_entities}] Processing: {entity_name} ({entity_type_value})"
            )

            linked_to = await self.detect_and_link_aliases_for_entity(
                entity_name, entity_type_value
            )

            stats["processed"] += 1

            if linked_to:
                stats["links_created"] += len(linked_to)
                logger.info(
                    f"[Alias] ✓ SUCCESS: Created {len(linked_to)} IS_SAME_AS link(s) for '{entity_name}': {', '.join(linked_to)}"
                )
                print(f"  ✓ Created {len(linked_to)} link(s): {', '.join(linked_to)}")
            else:
                stats["no_candidates"] += 1
                logger.info(f"[Alias] - No aliases detected for '{entity_name}'")
                print(f"  - No aliases found")

            # Progress summary every 10 entities
            if idx % 10 == 0:
                print(
                    f"\n[Summary] Processed {idx}/{total_entities} | Links created: {stats['links_created']} | No candidates: {stats['no_candidates']}\n"
                )

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)

        # Final summary
        print(f"\n[Complete] Processed {stats['processed']}/{total_entities} entities")
        print(f"           Links created: {stats['links_created']}")
        print(f"           No candidates: {stats['no_candidates']}\n")

        logger.info(f"[Alias] ===== BATCH DETECTION COMPLETE =====")
        logger.info(
            f"[Alias] Final stats: {stats['processed']} processed, "
            f"{stats['links_created']} links created, "
            f"{stats['no_candidates']} with no candidates"
        )

        return stats


alias_detector = AliasDetectorService()
