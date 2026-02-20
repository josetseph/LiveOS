#!/usr/bin/env python3
"""
Manual Alias Detection Script

Run this to detect and link node aliases in your existing knowledge graph.
This creates IS_SAME_AS relationships between nodes that refer to the same
real-world person/place/thing/concept based on LLM analysis of their contexts.

Usage:
    python scripts/detect_aliases.py                        # Process all node types (limit 10000 each)
    python scripts/detect_aliases.py --label Entity         # Process only Entity nodes
    python scripts/detect_aliases.py --label Concept        # Process only Concept nodes
    python scripts/detect_aliases.py --type Person          # Only Person entities
    python scripts/detect_aliases.py --limit 500            # Process up to 500 nodes per label
    python scripts/detect_aliases.py --dry-run              # Show what would be done (no changes)

Examples:
    # Process all Person entities
    python scripts/detect_aliases.py --label Entity --type Person --limit 200

    # Process Concept nodes (e.g., "AI" vs "Artificial Intelligence")
    python scripts/detect_aliases.py --label Concept --limit 100

    # Test on first 10 entities without making changes
    python scripts/detect_aliases.py --limit 10 --dry-run

    # Full run on all entity types
    python scripts/detect_aliases.py --limit 1000
"""

import asyncio
import sys
import os
import argparse
from datetime import datetime

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.alias_detector import alias_detector
from app.services.graph import graph_service
from app.core.log import get_logger

logger = get_logger("AliasScript")


def get_identifier_property(label: str) -> str:
    """Map node label to its identifier property."""
    mapping = {
        "Entity": "name",
        "Concept": "name",
        "Task": "name",
        "Persona": "trait",
        "Reference": "title",
    }
    return mapping.get(label, "name")


async def show_alias_candidates(node_label: str, node_type: str | None, limit: int):
    """
    Show potential alias candidates with LLM analysis without creating links.

    This is the detailed dry-run mode that shows what WOULD be linked and why.
    """
    from app.services.alias_detector import alias_detector

    # Get identifier property for this label
    identifier_prop = get_identifier_property(node_label)

    # Build type filter (only for Entity nodes)
    type_filter = (
        f"{{type: '{node_type}'}}" if node_type and node_label == "Entity" else ""
    )

    # Get nodes to analyze
    query = f"""
    MATCH (n:{node_label} {type_filter})
    WHERE NOT (n)-[:IS_SAME_AS]->()
      AND n.summary IS NOT NULL
      AND size(n.summary) > 20
    RETURN n.{identifier_prop} as identifier_value,
           n.type as node_type,
           n.summary as summary
    LIMIT $limit
    """

    nodes = graph_service.execute_query(query, {"limit": limit})

    total_analyzed = 0
    total_would_link = 0
    potential_links = []

    for node in nodes:
        node_value = node["identifier_value"]
        node_type_val = node.get("node_type")  # Only Entity has type
        node_summary = node["summary"]

        # For non-Entity labels, node_type is None
        if node_label == "Entity" and not node_type_val:
            continue

        type_info = f" ({node_type_val})" if node_type_val else ""
        print(f"[*] Analyzing: {node_value}{type_info} [{node_label}]")

        # Find potential aliases
        candidates = await alias_detector.find_potential_aliases(
            node_value=node_value,
            node_label=node_label,
            identifier_property=identifier_prop,
            node_type=node_type_val,
            limit=3,
        )

        if not candidates:
            print("   [+] No potential aliases found\n")
            total_analyzed += 1
            continue

        print(f"   Found {len(candidates)} potential candidates:")

        for candidate in candidates:
            candidate_value = candidate["identifier_value"]
            candidate_summary = candidate.get("summary", "")

            if not candidate_summary or len(candidate_summary) < 20:
                print(f"   [-] {candidate_value} (insufficient context)")
                continue

            # LLM analysis
            relationship_type, reason = await alias_detector.compare_entities_with_llm(
                node_value, node_summary, candidate_value, candidate_summary
            )

            # Show result
            if relationship_type:
                rel_label = relationship_type.replace("_", " ")
                print(f"   [→] {rel_label}: {candidate_value}")
                print(f"      Reason: {reason}")
                total_would_link += 1
                potential_links.append(
                    {
                        "entity1": node_value,
                        "entity2": candidate_value,
                        "relationship": relationship_type,
                        "reason": reason,
                    }
                )
            else:
                print(f"   [-] NO RELATIONSHIP: {candidate_value}")
                print(f"      Reason: {reason}")

        print()
        total_analyzed += 1

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.2)

    # Summary
    print("\n" + "=" * 80)
    print("CANDIDATE ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Entities Analyzed:     {total_analyzed}")
    print(f"Relationships Found:   {total_would_link}")
    print(f"Decision:              LLM determines type")
    print("=" * 80 + "\n")

    if potential_links:
        print("Relationships that would be created:\n")
        for i, link in enumerate(potential_links, 1):
            rel_label = link["relationship"].replace("_", " ")
            print(f"{i:2d}. '{link['entity1']}' ↔ '{link['entity2']}'")
            print(f"    Type: {rel_label}")
            print(f"    Reason: {link['reason']}\n")

        print("[TIP] To create these links, run without --show-candidates:")
        print(f"   python scripts/detect_aliases.py --limit {limit}\n")
    else:
        print("[OK] No alias links would be created with current threshold.\n")


async def main():
    parser = argparse.ArgumentParser(
        description="Detect and link node aliases using LLM-based context comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--label",
        type=str,
        default="All",
        choices=["All", "Entity", "Concept", "Task", "Persona", "Reference"],
        help="Node label to process (default: All)",
    )

    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="For Entity label only: filter by type (e.g., Person, Place, Organization)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum number of nodes to process (default: 10000)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    parser.add_argument(
        "--show-candidates",
        action="store_true",
        help="Show potential alias candidates with LLM reasoning (no changes made)",
    )

    args = parser.parse_args()

    # Determine which labels to process
    if args.label == "All":
        labels_to_process = ["Entity", "Concept", "Task", "Persona", "Reference"]
    else:
        labels_to_process = [args.label]

    print("\n" + "=" * 80)
    print("RELATIONSHIP DETECTION SCRIPT")
    print("=" * 80)
    if args.label == "All":
        print(f"Node Labels:  All (Entity, Concept, Task, Persona, Reference)")
    else:
        print(f"Node Label:   {args.label}")
    if args.label == "Entity" and args.type:
        print(f"Entity Type:  {args.type}")
    print(f"Limit:        {args.limit} per label")
    print(
        f"Decision:     LLM determines relationship type (IS_SAME_AS, IS_VARIANT_OF, IS_SIMILAR_TO, RELATED_TO)"
    )
    if args.show_candidates:
        print("Mode:         SHOW CANDIDATES (analysis only, no changes)")
    elif args.dry_run:
        print("Mode:         DRY RUN (no changes)")
    else:
        print("Mode:         LIVE (will modify graph)")
    print("=" * 80 + "\n")

    if args.dry_run and not args.show_candidates:
        print("[DRY RUN] No changes will be made to the graph\n")
    elif args.show_candidates:
        print("[ANALYSIS] Will show potential relationships with LLM reasoning\n")

    # Process each label
    total_stats = {"processed": 0, "links_created": 0, "no_candidates": 0}
    overall_start = datetime.now()

    for label in labels_to_process:
        # Get identifier property for this label
        identifier_prop = get_identifier_property(label)

        print(f"\n[{label}] Counting eligible nodes...")
        # Count total nodes
        type_filter = (
            f"{{type: '{args.type}'}}" if args.type and label == "Entity" else ""
        )
        count_query = f"""
        MATCH (n:{label} {type_filter})
        WHERE NOT (n)-[:IS_SAME_AS]->()
          AND n.summary IS NOT NULL
          AND size(n.summary) > 20
        RETURN count(n) as total
        """

        count_result = graph_service.execute_query(count_query, {})
        total_candidates = count_result[0]["total"] if count_result else 0

        print(f"\n{'=' * 80}")
        print(f"Processing {label} nodes")
        print(f"{'=' * 80}")
        print(f"Found {total_candidates} candidate {label} nodes for alias detection")
        print(f"   (Will process first {min(args.limit, total_candidates)})\n")

        if total_candidates == 0:
            print(f"[OK] No {label} nodes to process. Skipping.\n")
            continue

        # Confirm if not dry run or show-candidates (only ask once for first label)
        if (
            not args.dry_run
            and not args.show_candidates
            and label == labels_to_process[0]
        ):
            response = input(
                "Continue with LIVE run? This will create IS_SAME_AS links. [y/N]: "
            )
            if response.lower() != "y":
                print("[CANCELLED]")
                return

        # Run detection
        start_time = datetime.now()
        print(f"[{label}] Start time: {start_time.strftime('%H:%M:%S')}")

        if args.show_candidates:
            print(f"\n[*] Analyzing potential {label} alias candidates...\n")
            await show_alias_candidates(label, args.type, args.limit)
        elif args.dry_run:
            print(f"\n[*] Analyzing {label} nodes (DRY RUN)...\n")
            print(
                "[INFO] Basic dry-run mode. Use --show-candidates for detailed analysis."
            )
            print(
                f"    Would process {min(args.limit, total_candidates)} {label} nodes looking for aliases.\n"
            )
        else:
            print(f"\n[*] Running alias detection on {label} nodes...\n")
            # For now, batch detection only supports Entity (keep for backward compatibility)
            if label == "Entity":
                stats = await alias_detector.batch_detect_aliases(
                    entity_type=args.type, limit=args.limit
                )
                total_stats["processed"] += stats["processed"]
                total_stats["links_created"] += stats["links_created"]
                total_stats["no_candidates"] += stats["no_candidates"]

                duration = (datetime.now() - start_time).total_seconds()
                end_time = datetime.now()

                # Print results for this label
                print("\n" + "-" * 80)
                print(f"{label} ALIAS DETECTION COMPLETE")
                print("-" * 80)
                print(f"End time:              {end_time.strftime('%H:%M:%S')}")
                print(f"Entities Processed:    {stats['processed']}")
                print(f"Links Created:         {stats['links_created']}")
                print(f"No Candidates:         {stats['no_candidates']}")
                print(
                    f"Duration:              {duration:.1f}s ({duration/60:.1f} minutes)"
                )
                print(
                    f"Average per entity:    {duration/max(stats['processed'], 1):.2f}s"
                )
                print("-" * 80 + "\n")
            else:
                # For other labels, process one by one
                print(f"[WARN] Batch mode not implemented for {label} nodes yet.")
                print("    Use ingestion workflow for automatic alias detection.\n")
                continue

    # Show overall summary if processing multiple labels
    if len(labels_to_process) > 1 and not args.dry_run and not args.show_candidates:
        overall_duration = (datetime.now() - overall_start).total_seconds()
        overall_end = datetime.now()
        print("\n" + "=" * 80)
        print("OVERALL ALIAS DETECTION COMPLETE")
        print("=" * 80)
        print(f"Started:               {overall_start.strftime('%H:%M:%S')}")
        print(f"Finished:              {overall_end.strftime('%H:%M:%S')}")
        print(f"Total Nodes Processed: {total_stats['processed']}")
        print(f"Total Links Created:   {total_stats['links_created']}")
        print(f"No Candidates:         {total_stats['no_candidates']}")
        print(
            f"Total Duration:        {overall_duration:.1f}s ({overall_duration/60:.1f} minutes)"
        )
        print(
            f"Average per node:      {overall_duration/max(total_stats['processed'], 1):.2f}s"
        )
        print("=" * 80 + "\n")

        if total_stats["links_created"] > 0:
            print("Next Steps:")
            print("   1. Review created IS_SAME_AS links in Neo4j Browser")
            print("   2. Run test queries to verify alias resolution works")
            print("   3. If needed, manually delete incorrect links:")
            print("      MATCH ()-[r:IS_SAME_AS]->() WHERE r.confidence < 0.9 DELETE r")
            print()

    # Show some examples of created links (from all labels)
    if not args.dry_run and not args.show_candidates:
        print("\nSample IS_SAME_AS links created (all labels):\n")
        # Query for recent links across all processed labels
        for label in labels_to_process:
            identifier_prop = get_identifier_property(label)
            sample_query = f"""
            MATCH (alias:{label})-[r:IS_SAME_AS]->(canonical:{label})
            WHERE r.detected_at >= datetime() - duration({{hours: 1}})
            RETURN '{label}' as label,
                   alias.{identifier_prop} as alias, 
                   canonical.{identifier_prop} as canonical,
                   r.confidence as confidence,
                   r.reason as reason
            ORDER BY r.confidence DESC
            LIMIT 3
            """

            samples = graph_service.execute_query(sample_query, {})

            if samples:
                print(f"\n{label} links:")
                for i, link in enumerate(samples, 1):
                    print(
                        f"  {i}. '{link['alias']}' -> '{link['canonical']}' "
                        f"(confidence: {link['confidence']:.2f})"
                    )
                    print(f"     Reason: {link['reason']}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
