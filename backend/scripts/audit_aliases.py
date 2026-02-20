#!/usr/bin/env python3
"""
Audit IS_SAME_AS relationships for potential false positives.

This script:
1. Retrieves all IS_SAME_AS relationships
2. Shows context for both entities
3. Allows review and cleanup of incorrect links
"""

import sys
import os
from datetime import datetime

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import GraphService


def get_all_alias_links():
    """Retrieve all IS_SAME_AS relationships with entity details."""
    query = """
    MATCH (n1)-[r:IS_SAME_AS]->(n2)
    RETURN 
        n1.name as name1,
        n1.id as id1,
        labels(n1)[0] as type1,
        n1.summary as summary1,
        n2.name as name2,
        n2.id as id2,
        labels(n2)[0] as type2,
        n2.summary as summary2,
        r.confidence as confidence,
        r.reasoning as reasoning,
        r.created_at as created_at
    ORDER BY r.created_at DESC
    """

    graph_service = GraphService()
    results = graph_service.execute_query(query)
    return results


def get_entity_context(entity_id, entity_type):
    """Get detailed context about an entity."""
    query = """
    MATCH (n {id: $entity_id})
    OPTIONAL MATCH (n)-[r]-(related)
    RETURN 
        n.name as name,
        n.summary as summary,
        COUNT(DISTINCT related) as connection_count,
        COLLECT(DISTINCT type(r))[0..5] as relationship_types,
        COLLECT(DISTINCT related.name)[0..5] as related_names
    """

    graph_service = GraphService()
    results = graph_service.execute_query(query, {"entity_id": entity_id})
    return results[0] if results else None


def display_link(record, index, total):
    """Display a single alias link for review."""
    print(f"\n{'='*80}")
    print(f"Link {index}/{total} - Created: {record['created_at']}")
    print(f"{'='*80}")

    print(f"\n[Entity 1] {record['name1']} ({record['type1']})")
    print(f"  ID: {record['id1']}")
    if record.get("summary1"):
        print(f"  Summary: {record['summary1'][:200]}...")

    print(f"\n     ↕️  IS_SAME_AS")

    print(f"\n[Entity 2] {record['name2']} ({record['type2']})")
    print(f"  ID: {record['id2']}")
    if record.get("summary2"):
        print(f"  Summary: {record['summary2'][:200]}...")

    print(f"\n[Link Details]")
    print(f"  Confidence: {record.get('confidence', 0):.2%}")
    reasoning = record.get("reasoning") or "No reasoning provided"
    print(f"  Reasoning: {reasoning}")


def delete_link(id1, id2):
    """Delete IS_SAME_AS relationship between two entities."""
    query = """
    MATCH (n1 {id: $id1})-[r:IS_SAME_AS]-(n2 {id: $id2})
    DELETE r
    RETURN COUNT(r) as deleted_count
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query, {"id1": id1, "id2": id2})
    return result[0]["deleted_count"] if result else 0


def analyze_suspicious_patterns():
    """Identify potentially problematic links."""
    query = """
    MATCH (n1)-[r:IS_SAME_AS]->(n2)
    WHERE n1.name <> n2.name  // Different names
    WITH n1, n2, r,
         size(n1.name) as len1,
         size(n2.name) as len2
    WHERE abs(len1 - len2) > 10  // Significant length difference
    RETURN 
        n1.name as name1,
        n2.name as name2,
        r.confidence as confidence,
        r.reasoning as reasoning
    ORDER BY r.confidence DESC
    LIMIT 20
    """

    graph_service = GraphService()
    return graph_service.execute_query(query)


def main():
    """Main execution."""
    print("🔍 Alias Link Auditor")
    print("=" * 80)

    # Get all links
    print("\nRetrieving all IS_SAME_AS links...")
    links = get_all_alias_links()

    if not links:
        print("No IS_SAME_AS links found.")
        return

    print(f"Found {len(links)} alias links.")

    # Show summary stats
    print(f"\n📊 Summary Statistics:")
    print(f"  Total links: {len(links)}")

    avg_conf = sum(r.get("confidence", 0) for r in links) / len(links) if links else 0
    print(f"  Average confidence: {avg_conf:.2%}")

    # Show suspicious patterns
    print("\n🚨 Potentially Suspicious Links (large name differences):")
    suspicious = analyze_suspicious_patterns()

    if suspicious:
        for i, s in enumerate(suspicious[:10], 1):
            print(f"\n  {i}. '{s['name1']}' ↔ '{s['name2']}'")
            print(f"     Confidence: {s['confidence']:.2%}")
            reasoning = s.get("reasoning") or "N/A"
            print(f"     Reasoning: {reasoning[:100] if reasoning else 'N/A'}")
    else:
        print("  None found (this is good!)")

    # Interactive review
    print("\n" + "=" * 80)
    print("Interactive Review")
    print("=" * 80)
    print("\nOptions:")
    print("  [Enter] - Next link")
    print("  d - Delete this link (false positive)")
    print("  c - Show more context")
    print("  q - Quit")

    deleted_count = 0

    for i, record in enumerate(links, 1):
        display_link(record, i, len(links))

        while True:
            choice = input("\n> ").strip().lower()

            if choice == "":
                break  # Next link
            elif choice == "q":
                print(f"\n✅ Review complete. Deleted {deleted_count} false positives.")
                return
            elif choice == "d":
                confirm = input("⚠️  Delete this link? (yes/no): ").strip().lower()
                if confirm == "yes":
                    count = delete_link(record["id1"], record["id2"])
                    if count > 0:
                        print(
                            f"✅ Deleted link between '{record['name1']}' and '{record['name2']}'"
                        )
                        deleted_count += 1
                    else:
                        print("❌ Failed to delete link")
                break
            elif choice == "c":
                print("\n[Additional Context - Entity 1]")
                ctx1 = get_entity_context(record["id1"], record["type1"])
                if ctx1:
                    print(f"  Connections: {ctx1['connection_count']}")
                    print(
                        f"  Relationships: {', '.join(ctx1['relationship_types'][:5])}"
                    )
                    print(f"  Related to: {', '.join(ctx1['related_names'][:5])}")

                print("\n[Additional Context - Entity 2]")
                ctx2 = get_entity_context(record["id2"], record["type2"])
                if ctx2:
                    print(f"  Connections: {ctx2['connection_count']}")
                    print(
                        f"  Relationships: {', '.join(ctx2['relationship_types'][:5])}"
                    )
                    print(f"  Related to: {', '.join(ctx2['related_names'][:5])}")
            else:
                print("Invalid choice. Use [Enter], d, c, or q")

    print(f"\n✅ Review complete. Deleted {deleted_count} false positives.")


if __name__ == "__main__":
    main()
