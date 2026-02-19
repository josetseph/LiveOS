"""
Summary Quality Verification Script
Checks that all knowledge graph nodes have properly generated summaries.
"""

import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import graph_service
from app.core.log import get_logger

logger = get_logger("SummaryVerification")


def verify_summaries():
    """Verify summary quality across all knowledge graph node types."""

    print("\n" + "=" * 80)
    print("SUMMARY QUALITY VERIFICATION")
    print("=" * 80 + "\n")

    node_types = [
        ("Concept", "summary"),
        ("Entity", "summary"),
        ("Task", "description"),
        ("Persona", "summary"),
        ("Reference", "summary"),
    ]

    for node_type, summary_field in node_types:
        print(f"\n📌 {node_type.upper()}S")
        print("-" * 80)

        # 1. Count total vs with summaries
        count_query = f"""
        MATCH (n:{node_type})
        RETURN count(n) as total,
               count(n.{summary_field}) as with_summary,
               sum(CASE WHEN n.{summary_field} IS NOT NULL AND size(n.{summary_field}) > 0 THEN 1 ELSE 0 END) as non_empty_summary
        """
        result = graph_service.execute_query(count_query)
        if result:
            r = result[0]
            total = r["total"]
            with_summary = r["with_summary"]
            non_empty = r["non_empty_summary"]
            empty = total - non_empty

            print(f"Total {node_type}s: {total}")
            print(
                f"With {summary_field}: {with_summary} ({100*with_summary/total if total > 0 else 0:.1f}%)"
            )
            print(f"Non-empty: {non_empty}")
            if empty > 0:
                print(f"⚠️  Empty/missing: {empty}")

        # 2. Summary length distribution
        length_query = f"""
        MATCH (n:{node_type})
        WHERE n.{summary_field} IS NOT NULL
        WITH size(n.{summary_field}) as length
        RETURN min(length) as min_length,
               max(length) as max_length,
               avg(length) as avg_length,
               percentileCont(length, 0.5) as median_length
        """
        result = graph_service.execute_query(length_query)
        if result and result[0]["min_length"] is not None:
            r = result[0]
            print(f"\nSummary Length Stats:")
            print(f"  Min: {r['min_length']} chars")
            print(f"  Max: {r['max_length']} chars")
            print(f"  Avg: {r['avg_length']:.1f} chars")
            print(f"  Median: {r['median_length']:.1f} chars")

        # 3. Sample summaries for quality review
        sample_query = f"""
        MATCH (n:{node_type})
        WHERE n.{summary_field} IS NOT NULL AND size(n.{summary_field}) > 0
        WITH n, rand() as r
        ORDER BY r
        LIMIT 5
        RETURN n.name as name, 
               n.{summary_field} as summary
        """

        # Special handling for different node types
        if node_type == "Entity":
            sample_query = f"""
            MATCH (n:{node_type})
            WHERE n.summary IS NOT NULL AND size(n.summary) > 0
            WITH n, rand() as r
            ORDER BY r
            LIMIT 5
            RETURN n.name as name, 
                   n.type as entity_type,
                   n.summary as summary
            """
        elif node_type == "Task":
            sample_query = f"""
            MATCH (n:{node_type})
            WHERE n.description IS NOT NULL AND size(n.description) > 0
            WITH n, rand() as r
            ORDER BY r
            LIMIT 5
            RETURN n.description as name, 
                   n.status as status,
                   n.description as summary
            """
        elif node_type == "Persona":
            sample_query = f"""
            MATCH (n:{node_type})
            WHERE n.summary IS NOT NULL AND size(n.summary) > 0
            WITH n, rand() as r
            ORDER BY r
            LIMIT 5
            RETURN n.trait as name, 
                   n.summary as summary
            """

        results = graph_service.execute_query(sample_query)

        if results:
            print(f"\n📝 Sample {node_type}s (Random 5):")
            for i, row in enumerate(results, 1):
                name = row.get("name", "Unknown")[:60]
                summary = row.get("summary", "N/A")

                if node_type == "Entity":
                    entity_type = row.get("entity_type", "Unknown")
                    print(f"\n  {i}. [{entity_type}] {name}")
                elif node_type == "Task":
                    status = row.get("status", "Unknown")
                    print(f"\n  {i}. [Status: {status}] {name}")
                elif node_type == "Persona":
                    print(f"\n  {i}. Trait: {name}")
                else:
                    print(f"\n  {i}. {name}")

                # Wrap summary text
                if summary and len(summary) > 120:
                    print(f"     Summary: {summary[:120]}...")
                else:
                    print(f"     Summary: {summary}")
        else:
            print(f"⚠️  No samples found with summaries")

    # 4. Check for nodes with missing summaries (quality issue detection)
    print(f"\n\n⚠️  QUALITY ISSUES")
    print("-" * 80)

    issues_found = False

    for node_type, summary_field in node_types:
        missing_query = f"""
        MATCH (n:{node_type})
        WHERE n.{summary_field} IS NULL OR size(n.{summary_field}) = 0
        RETURN n.name as name
        LIMIT 5
        """

        if node_type == "Task":
            missing_query = f"""
            MATCH (n:{node_type})
            WHERE n.description IS NULL OR size(n.description) = 0
            RETURN n
            LIMIT 5
            """

        results = graph_service.execute_query(missing_query)

        if results:
            issues_found = True
            print(f"\n{node_type}s with missing/empty {summary_field}:")
            for row in results:
                if node_type == "Task":
                    print(f"  • Task node with no description")
                else:
                    name = row.get("name", "Unknown")[:60]
                    print(f"  • {name}")

    if not issues_found:
        print("✅ No quality issues found - all nodes have summaries!")

    # 5. Summary-to-Source note linking
    print(f"\n\n🔗 SUMMARY GROUNDING (Sample)")
    print("-" * 80)
    print("Checking if summaries reference their source notes properly...")

    grounding_query = """
    MATCH (n:Concept)
    WHERE n.summary IS NOT NULL
    WITH n LIMIT 1
    OPTIONAL MATCH (note:Note)-[:CONTRIBUTES_TO]->(n)
    RETURN n.name as concept_name,
           n.summary as concept_summary,
           collect(note.title)[0..3] as source_notes,
           count(note) as note_count
    """

    result = graph_service.execute_query(grounding_query)
    if result and result[0]:
        r = result[0]
        print(f"\nExample Concept: {r['concept_name']}")
        print(f"Summary: {r['concept_summary'][:150]}...")
        print(f"Grounded by {r['note_count']} note(s):")
        for note_title in r["source_notes"]:
            if note_title:
                print(f"  • {note_title[:60]}")

    print("\n" + "=" * 80)
    print("SUMMARY VERIFICATION COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    verify_summaries()
