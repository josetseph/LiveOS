"""
Clean up bad alias relationships created by poor LLM quality.
Deletes relationships detected today via llm_context_analysis method.
"""

import sys

sys.path.append(".")

from app.services.graph import graph_service


def cleanup_today_relationships():
    """Delete alias relationships created today by LLM."""

    print("\n" + "=" * 80)
    print("CLEANUP BAD ALIAS RELATIONSHIPS")
    print("=" * 80)

    # First, count what will be deleted
    count_query = """
    MATCH ()-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-()
    WHERE r.method = 'llm_context_analysis' 
      AND r.detected_at >= datetime('2026-02-20T00:00:00')
    RETURN count(r) as total
    """

    result = graph_service.execute_query(count_query)
    total = result[0]["total"] if result else 0

    print(f"\nFound {total} alias relationships created today via LLM")

    if total == 0:
        print("Nothing to delete.")
        return

    # Show sample of what will be deleted
    sample_query = """
    MATCH (e1)-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-(e2)
    WHERE r.method = 'llm_context_analysis' 
      AND r.detected_at >= datetime('2026-02-20T00:00:00')
    RETURN e1.name as entity1, type(r) as rel_type, e2.name as entity2, r.context as reason
    LIMIT 10
    """

    samples = graph_service.execute_query(sample_query)

    print("\nSample relationships to be deleted:")
    print("-" * 80)
    for i, row in enumerate(samples, 1):
        entity1 = row["entity1"]
        entity2 = row["entity2"]
        rel_type = row["rel_type"]
        reason = (
            row["reason"][:80] + "..." if len(row["reason"]) > 80 else row["reason"]
        )
        print(f"{i}. {entity1} -[{rel_type}]-> {entity2}")
        print(f"   Reason: {reason}\n")

    # Confirm deletion
    confirm = input(f"\nDelete all {total} relationships? (yes/no): ").strip().lower()

    if confirm != "yes":
        print("Cancelled.")
        return

    # Delete relationships
    delete_query = """
    MATCH ()-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-()
    WHERE r.method = 'llm_context_analysis' 
      AND r.detected_at >= datetime('2026-02-20T00:00:00')
    DELETE r
    RETURN count(*) as deleted
    """

    result = graph_service.execute_query(delete_query)
    deleted = result[0]["deleted"] if result else 0

    print(f"\n✅ Deleted {deleted} bad alias relationships")
    print("=" * 80)


if __name__ == "__main__":
    cleanup_today_relationships()
