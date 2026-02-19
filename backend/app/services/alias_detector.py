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
    """Detects and links node aliases using LLM-based context comparison"""

    def __init__(self):
        self.confidence_threshold = 0.98  # How confident LLM must be to merge

    async def find_potential_aliases(
        self, 
        node_value: str,
        node_label: str = "Entity",
        identifier_property: str = "name",
        node_type: Optional[str] = None,
        limit: int = 5
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
        # Exclude candidates we already have IS_SAME_AS relationships with (either direction)
        query = f"""
        MATCH (n:{node_label})
        WHERE n.{identifier_property} <> $value
          {type_filter}
          AND NOT EXISTS {{
            MATCH (source:{node_label} {{{identifier_property}: $value}})
            MATCH (source)-[:IS_SAME_AS]-(n)
          }}
          AND (
            // Levenshtein distance < 4 (allows 3 char typos)
            apoc.text.distance(toLower(n.{identifier_property}), toLower($value)) < 4
            OR
            // One name contains the other (at least 4 chars)
            (size($value) >= 4 AND toLower(n.{identifier_property}) CONTAINS toLower($value))
            OR
            (size(n.{identifier_property}) >= 4 AND toLower($value) CONTAINS toLower(n.{identifier_property}))
            OR
            // Same initials for compound names
            (size(split(n.{identifier_property}, ' ')) > 1 AND size(split($value, ' ')) > 1 AND
             substring(n.{identifier_property}, 0, 1) = substring($value, 0, 1))
            OR
            // Token overlap (at least 50% shared words)
            size([word IN split(toLower(n.{identifier_property}), ' ') WHERE word IN split(toLower($value), ' ')]) 
                >= toInteger(size(split(n.{identifier_property}, ' ')) * 0.5)
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
    ) -> tuple[bool, str, float]:
        """
        Use LLM to determine if two entities are the same by comparing their contexts.

        Args:
            entity1_name: Name of first entity
            entity1_context: Summary/context of first entity
            entity2_name: Name of second entity
            entity2_context: Summary/context of second entity

        Returns:
            (is_same, reason, confidence)
            - is_same: True if entities are the same
            - reason: LLM's explanation
            - confidence: 0.0-1.0 confidence score
        """
        prompt = f"""Are these two entities referring to the EXACT SAME real-world person, place, or thing?

CRITICAL: Answer YES only if they are THE EXACT SAME entity (not just similar or related).

ENTITY 1: "{entity1_name}"
Context: {entity1_context[:800]}

ENTITY 2: "{entity2_name}"
Context: {entity2_context[:800]}

# ANALYSIS CRITERIA

Consider these factors:
1. **Identity Test**: Would a knowledgeable person say these are THE EXACT SAME thing?
   - NOT just "related" or "similar" or "in the same family"
   - They must be IDENTICAL - the same individual, same organization, same specific object
2. **Biographical Consistency**: Do key facts match? (birth year, location, profession, affiliations)
3. **Contextual Overlap**: Do they appear in similar contexts or relationships?
4. **Contradiction Check**: Are there contradicting facts that prove they're DIFFERENT entities?
   - Example: Different birth years, different nationalities, different professions
5. **Name Variation Types**:
   - Abbreviations: "J.K. Rowling" vs "Joanne Rowling" ✓
   - Nicknames: "Bill Gates" vs "William Gates" ✓
   - Titles: "Dr. Smith" vs "Smith" ✓
   - Common name collision: "Michael Jordan" (basketball) vs "Michael Jordan" (professor) ✗

# CRITICAL DISTINCTIONS (Must be DIFFERENT entities)

**Generic vs Specific**: Do NOT link abstract concepts to specific instances
- "programming language" vs "Python" ✗ (generic term vs specific language)
- "city" vs "Paris" ✗ (category vs specific instance)
- "smartphone" vs "iPhone" ✗ (category vs specific product)

**Type vs Member**: Do NOT link categories to their members
- "musical instrument" vs "guitar" ✗ (category vs member)
- "company" vs "Microsoft" ✗ (type vs instance)
- "politician" vs "Angela Merkel" ✗ (role vs person)

**Related but Different**: Do NOT link similar but distinct entities (THIS IS THE MOST COMMON ERROR)
- "violin" vs "viola" ✗ (related instruments from same family, but DIFFERENT instruments)
- "piano" vs "harpsichord" ✗ (both keyboard instruments, but DIFFERENT)
- "Harvard University" vs "MIT" ✗ (related institutions, but DIFFERENT)
- "iPhone 14" vs "iPhone 15" ✗ (same product line, but DIFFERENT models)
- "brother" vs "sister" ✗ (related family roles, but DIFFERENT)

**Same Family ≠ Same Entity**: Being in the same category/family does NOT make them the same
- Two instruments in the same family are DIFFERENT instruments
- Two companies in the same industry are DIFFERENT companies
- Two people in the same profession are DIFFERENT people

# IMPORTANT
- Only link if they refer to THE EXACT SAME real-world entity (same person, same place, same organization, same specific thing)
- "Related" ≠ "Same" | "Similar" ≠ "Same" | "Same type" ≠ "Same entity"
- If one is generic/abstract and the other is specific, answer NO
- If contexts describe completely different domains/activities, they're probably DIFFERENT entities
- If there's insufficient information to decide, answer UNCERTAIN
- Be conservative - false positives (wrong merge) are worse than false negatives (missed merge)

# OUTPUT FORMAT

Answer: [YES/NO/UNCERTAIN]
Confidence: [0-100]
Reason: [One sentence explanation focusing on key evidence]

# EXAMPLES

ENTITY 1: "Elon Musk"
Context: CEO of Tesla and SpaceX, founded in 2002. Born in South Africa, moved to US.

ENTITY 2: "Elon"
Context: Founded PayPal in 1999, later started SpaceX. Known for electric vehicles.

Answer: YES
Confidence: 95
Reason: Both contexts describe the same person - founder of SpaceX, involved in electric vehicles and PayPal.

---

ENTITY 1: "Michael Jordan"
Context: NBA basketball player, Chicago Bulls, won 6 championships, retired 2003.

ENTITY 2: "Michael Jordan"
Context: Professor of Computer Science at UC Berkeley, researches machine learning.

Answer: NO
Confidence: 99
Reason: Completely different professions and contexts - one is basketball, other is academia.

---

ENTITY 1: "Marie Curie"
Context: Physicist who discovered radium.

ENTITY 2: "Maria Sklodowska"
Context: Scientist born in Poland, moved to France.

Answer: UNCERTAIN
Confidence: 60
Reason: Contexts are related (both scientists) but insufficient detail to confirm they're the same person.

---

ENTITY 1: "software company"
Context: A type of business organization that develops and sells software products.

ENTITY 2: "Microsoft"
Context: A technology company founded by Bill Gates in 1975, known for Windows operating system.

Answer: NO
Confidence: 99
Reason: "Software company" is a generic category, while "Microsoft" is a specific company instance - these are different entities.

---

ENTITY 1: "saxophone"
Context: A woodwind instrument invented by Adolphe Sax in 1840s, uses a single reed.

ENTITY 2: "clarinet"
Context: A woodwind instrument with a single reed, cylindrical bore, used in orchestras and jazz.

Answer: NO
Confidence: 99
Reason: These are DIFFERENT instruments - despite both being single-reed woodwinds, they have distinct designs, fingering systems, tonal characteristics, and are recognized as separate instruments by musicians.

---

Now analyze the entities above:
"""

        try:
            response = await llm_service.generate(prompt, temperature=0.1)

            # Parse response
            is_same = False
            confidence = 0.0
            reason = "No reason provided"

            lines = response.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("Answer:"):
                    answer_part = line.replace("Answer:", "").strip().upper()
                    is_same = "YES" in answer_part
                elif line.startswith("Confidence:"):
                    conf_str = line.replace("Confidence:", "").strip().replace("%", "")
                    try:
                        confidence = float(conf_str) / 100.0
                    except ValueError:
                        confidence = 0.5
                elif line.startswith("Reason:"):
                    reason = line.replace("Reason:", "").strip()

            logger.info(
                f"[Alias] Compared '{entity1_name}' vs '{entity2_name}': "
                f"{'SAME' if is_same else 'DIFFERENT'} (confidence: {confidence:.2f}) - {reason}"
            )

            return is_same, reason, confidence

        except Exception as e:
            logger.error(f"[Alias] LLM comparison failed: {e}")
            return False, f"Error: {e}", 0.0

    async def create_alias_link(
        self,
        alias_value: str,
        canonical_value: str,
        node_label: str,
        identifier_property: str,
        confidence: float,
        reason: str,
    ):
        """
        Create an IS_SAME_AS relationship between alias and canonical node.

        Does NOT merge nodes - just creates relationship for retrieval to follow.
        This is non-destructive and allows manual review/correction later.

        Args:
            alias_value: The alias/variant value
            canonical_value: The canonical/preferred value
            node_label: Node label (Entity, Concept, etc)
            identifier_property: Property name (name, trait, title)
            confidence: LLM confidence score (0.0-1.0)
            reason: LLM's reasoning for the merge
        """
        query = f"""
        MATCH (alias:{node_label} {{{identifier_property}: $alias_value}})
        MATCH (canonical:{node_label} {{{identifier_property}: $canonical_value}})
        
        // Create IS_SAME_AS relationship (if doesn't exist)
        MERGE (alias)-[r:IS_SAME_AS]->(canonical)
        SET r.confidence = $confidence,
            r.reason = $reason,
            r.detected_at = datetime(),
            r.method = 'llm_context_comparison'
        
        RETURN alias.{identifier_property} as alias, canonical.{identifier_property} as canonical
        """

        result = graph_service.execute_query(
            query,
            {
                "alias_value": alias_value,
                "canonical_value": canonical_value,
                "confidence": confidence,
                "reason": reason,
            },
        )

        if result:
            logger.info(
                f"[Alias] Created IS_SAME_AS ({node_label}): '{alias_value}' -> '{canonical_value}' (confidence: {confidence:.2f})"
            )
        else:
            logger.warning(
                f"[Alias] Failed to create IS_SAME_AS link ({node_label}): {alias_value} -> {canonical_value}"
            )

    async def detect_and_link_aliases_for_node(
        self, 
        node_value: str,
        node_label: str,
        identifier_property: str = "name",
        node_type: Optional[str] = None
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
        candidates = await self.find_potential_aliases(
            node_value, node_label, identifier_property, node_type
        )

        if not candidates:
            logger.debug(f"[Alias] No potential aliases found for '{node_value}'")
            return []

        logger.info(
            f"[Alias] Found {len(candidates)} potential candidate(s) for '{node_value}' ({node_label})"
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

            # LLM comparison
            print(f"  → Comparing with: {candidate_value}")
            is_same, reason, confidence = await self.compare_entities_with_llm(
                node_value, node_summary, candidate_value, candidate_summary
            )

            # Only link if confidence meets threshold
            if is_same and confidence >= self.confidence_threshold:
                print(f"    ✓ Match confirmed (confidence: {confidence:.2%})")
                await self.create_alias_link(
                    alias_value=node_value,
                    canonical_value=candidate_value,
                    node_label=node_label,
                    identifier_property=identifier_property,
                    confidence=confidence,
                    reason=reason,
                )
                linked_to.append(candidate_value)
            elif is_same:
                print(f"    ✗ Match but confidence too low ({confidence:.2%} < {self.confidence_threshold:.2%})")
            else:
                print(f"    ✗ Not the same entity (confidence: {confidence:.2%})")
                # Only link to one canonical node
                break

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
            node_type=entity_type
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
        logger.info(f"[Alias] Processing {total_entities} entities")
        print(f"\n[Progress] Starting alias detection for {total_entities} entities...\n")

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
            print(f"[{idx}/{total_entities}] Processing: {entity_name} ({entity_type_value})")

            linked_to = await self.detect_and_link_aliases_for_entity(
                entity_name, entity_type_value
            )

            stats["processed"] += 1

            if linked_to:
                stats["links_created"] += len(linked_to)
                print(f"  ✓ Created {len(linked_to)} link(s): {', '.join(linked_to)}")
            else:
                stats["no_candidates"] += 1
                print(f"  - No aliases found")

            # Progress summary every 10 entities
            if idx % 10 == 0:
                print(f"\n[Summary] Processed {idx}/{total_entities} | Links created: {stats['links_created']} | No candidates: {stats['no_candidates']}\n")

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)

        # Final summary
        print(f"\n[Complete] Processed {stats['processed']}/{total_entities} entities")
        print(f"           Links created: {stats['links_created']}")
        print(f"           No candidates: {stats['no_candidates']}\n")

        logger.info(
            f"[Alias] Batch complete: {stats['processed']} processed, "
            f"{stats['links_created']} links created"
        )

        return stats


alias_detector = AliasDetectorService()
