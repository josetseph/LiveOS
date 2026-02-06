"""
Backfill script to generate summaries for entities that have "None yet." placeholder.

This script finds all entities linked to notes but missing real summaries,
and generates fresh summaries from the linked note content.
"""

import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import graph_service
from app.services.llm import llm_service
from app.services.embedding import embedding_service


def get_entities_needing_summaries(limit: int = 100) -> list[dict]:
    """Get entities with placeholder summaries that have linked notes."""
    query = """
    MATCH (n:Note)-[:MENTIONS]->(e:Entity)
    WHERE e.summary IS NULL OR e.summary = "" OR e.summary = "None yet."
    WITH e, collect(n)[0] as first_note
    RETURN DISTINCT e.name as name, labels(e)[0] as label, first_note.summary as note_summary
    LIMIT $limit
    """
    return graph_service.execute_query(query, {"limit": limit})


def get_concepts_needing_summaries(limit: int = 100) -> list[dict]:
    """Get concepts with placeholder summaries that have linked notes."""
    query = """
    MATCH (n:Note)-[:MENTIONS]->(c:Concept)
    WHERE c.summary IS NULL OR c.summary = "" OR c.summary = "None yet."
    WITH c, collect(n)[0] as first_note
    RETURN DISTINCT c.name as name, labels(c)[0] as label, first_note.summary as note_summary
    LIMIT $limit
    """
    return graph_service.execute_query(query, {"limit": limit})


def update_node_summary(name: str, label: str, context: str):
    """Generate and save a summary for a node."""
    if not context or not context.strip():
        print(f"  Skipping {name} - no context available")
        return False

    try:
        # Generate fresh summary
        summary_data = llm_service.generate_entity_summary(context, name, label)

        # Generate embedding
        text_to_embed = f"{summary_data['title']}: {summary_data['summary']}"
        new_embedding = embedding_service.embed_query(text_to_embed)

        # Save to graph
        graph_service.execute_query(
            f"MATCH (n:{label} {{name: $name}}) SET n.summary = $summary, n.title = $title, n.embedding = $embedding",
            {
                "name": name,
                "summary": summary_data["summary"],
                "title": summary_data["title"],
                "embedding": new_embedding,
            },
        )
        print(f"  ✓ {label}: {name} -> {summary_data['title']}")
        return True
    except Exception as e:
        print(f"  ✗ {label}: {name} - Error: {e}")
        return False


def main():
    print("=" * 60)
    print("BACKFILL SUMMARIES FOR ENTITIES WITH 'None yet.'")
    print("=" * 60)

    # Get counts first
    entity_count = graph_service.execute_query(
        """
        MATCH (e:Entity)
        WHERE e.summary IS NULL OR e.summary = "" OR e.summary = "None yet."
        RETURN count(e) as cnt
    """
    )[0]["cnt"]

    concept_count = graph_service.execute_query(
        """
        MATCH (c:Concept)
        WHERE c.summary IS NULL OR c.summary = "" OR c.summary = "None yet."
        RETURN count(c) as cnt
    """
    )[0]["cnt"]

    print(f"\nEntities needing summaries: {entity_count}")
    print(f"Concepts needing summaries: {concept_count}")

    if entity_count == 0 and concept_count == 0:
        print("\n✅ All nodes already have summaries!")
        return

    batch_size = 50
    total_updated = 0

    # Process entities
    print(f"\n--- Processing Entities (batch size: {batch_size}) ---")
    while True:
        entities = get_entities_needing_summaries(batch_size)
        if not entities:
            break

        for entity in entities:
            if update_node_summary(
                entity["name"], "Entity", entity.get("note_summary", "")
            ):
                total_updated += 1

        print(f"  Batch complete. Total updated: {total_updated}")

    # Process concepts
    print(f"\n--- Processing Concepts (batch size: {batch_size}) ---")
    while True:
        concepts = get_concepts_needing_summaries(batch_size)
        if not concepts:
            break

        for concept in concepts:
            if update_node_summary(
                concept["name"], "Concept", concept.get("note_summary", "")
            ):
                total_updated += 1

        print(f"  Batch complete. Total updated: {total_updated}")

    print(f"\n{'=' * 60}")
    print(f"COMPLETE: Updated {total_updated} node summaries")
    print("=" * 60)


if __name__ == "__main__":
    main()
