#!/usr/bin/env python3
"""
Script to merge duplicate nodes that differ only by case.
This is a one-time cleanup for nodes created before the lowercase normalization.

Usage: python scripts/merge_duplicate_nodes.py --dry-run
       python scripts/merge_duplicate_nodes.py --apply
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.graph import GraphService


def find_duplicates():
    """Find all nodes that differ only by case."""
    graph = GraphService()

    query = """
    MATCH (n:Indexable)
    WITH toLower(n.name) AS lower_name, collect(n) AS nodes, count(*) AS cnt
    WHERE cnt > 1
    RETURN lower_name, 
           [node IN nodes | {
               id: elementId(node), 
               name: node.name, 
               labels: labels(node),
               summary: node.summary,
               has_summary: node.summary IS NOT NULL
           }] AS node_details,
           cnt
    ORDER BY cnt DESC
    """

    return graph.execute_query(query, {})


def merge_duplicates(dry_run: bool = True):
    """
    Merge duplicate nodes by:
    1. Keeping the one with the best summary (longest, or has summary vs doesn't)
    2. Moving all relationships from other nodes to the keeper
    3. Deleting the duplicate nodes
    """
    graph = GraphService()
    duplicates = find_duplicates()

    if not duplicates:
        print("✅ No duplicate nodes found!")
        return

    print(f"Found {len(duplicates)} groups of duplicate nodes")

    total_merged = 0

    for dup_group in duplicates:
        lower_name = dup_group["lower_name"]
        nodes = dup_group["node_details"]

        print(f"\n{'─'*60}")
        print(f"Processing: '{lower_name}' ({len(nodes)} duplicates)")

        # Sort nodes by: has_summary (True first), then summary length
        def score_node(node):
            has_summary = node.get("has_summary", False)
            summary_len = len(node.get("summary") or "") if node.get("summary") else 0
            return (has_summary, summary_len)

        sorted_nodes = sorted(nodes, key=score_node, reverse=True)

        keeper = sorted_nodes[0]
        to_delete = sorted_nodes[1:]

        print(
            f"  Keeping: '{keeper['name']}' (summary: {len(keeper.get('summary') or '')} chars)"
        )
        for node in to_delete:
            print(f"  Merging into keeper: '{node['name']}'")

        if dry_run:
            print("  [DRY RUN] Would merge and delete duplicates")
            continue

        # For each duplicate, move its relationships to the keeper
        for dup_node in to_delete:
            dup_id = dup_node["id"]
            keeper_id = keeper["id"]

            # Move incoming relationships
            move_incoming = """
            MATCH (n) WHERE elementId(n) = $dup_id
            MATCH (k) WHERE elementId(k) = $keeper_id
            MATCH (other)-[r]->(n)
            WHERE other <> k
            WITH other, r, k, type(r) AS rel_type, properties(r) AS props
            CALL apoc.create.relationship(other, rel_type, props, k) YIELD rel
            DELETE r
            RETURN count(rel) AS moved
            """

            # Move outgoing relationships
            move_outgoing = """
            MATCH (n) WHERE elementId(n) = $dup_id
            MATCH (k) WHERE elementId(k) = $keeper_id
            MATCH (n)-[r]->(other)
            WHERE other <> k
            WITH other, r, k, type(r) AS rel_type, properties(r) AS props
            CALL apoc.create.relationship(k, rel_type, props, other) YIELD rel
            DELETE r
            RETURN count(rel) AS moved
            """

            try:
                # Try using APOC if available
                result1 = graph.execute_query(
                    move_incoming, {"dup_id": dup_id, "keeper_id": keeper_id}
                )
                result2 = graph.execute_query(
                    move_outgoing, {"dup_id": dup_id, "keeper_id": keeper_id}
                )
            except Exception as e:
                # Fallback without APOC - just log warning
                print(f"  ⚠️  Could not move relationships (APOC not available): {e}")
                print(f"  ⚠️  Deleting duplicate node without merging relationships")

            # Delete the duplicate node
            delete_query = """
            MATCH (n) WHERE elementId(n) = $dup_id
            DETACH DELETE n
            """
            graph.execute_query(delete_query, {"dup_id": dup_id})
            total_merged += 1

        # Rename keeper to lowercase if not already
        rename_query = """
        MATCH (n) WHERE elementId(n) = $keeper_id
        SET n.name = $new_name
        """
        graph.execute_query(
            rename_query, {"keeper_id": keeper["id"], "new_name": lower_name}
        )
        print(f"  ✅ Renamed keeper to lowercase: '{lower_name}'")

    print(f"\n{'='*60}")
    print(f"Total nodes merged: {total_merged}")
    print("=" * 60)


def simple_lowercase_rename(dry_run: bool = True):
    """
    Simple approach: Just rename all nodes to lowercase.
    This doesn't merge - it assumes you'll re-ingest data after.

    Use this if APOC is not installed.
    """
    graph = GraphService()

    # Find all nodes not already lowercase
    query = """
    MATCH (n:Indexable)
    WHERE n.name <> toLower(n.name)
    RETURN elementId(n) AS id, n.name AS name, toLower(n.name) AS lower_name
    LIMIT 1000
    """

    results = graph.execute_query(query, {})

    if not results:
        print("✅ All node names are already lowercase!")
        return

    print(f"Found {len(results)} nodes with non-lowercase names")

    if dry_run:
        print("\n[DRY RUN] Would rename:")
        for row in results[:20]:
            print(f"  '{row['name']}' -> '{row['lower_name']}'")
        if len(results) > 20:
            print(f"  ... and {len(results) - 20} more")
        return

    # Rename each node
    for row in results:
        rename_query = """
        MATCH (n) WHERE elementId(n) = $id
        SET n.name = $new_name
        """
        graph.execute_query(
            rename_query, {"id": row["id"], "new_name": row["lower_name"]}
        )

    print(f"✅ Renamed {len(results)} nodes to lowercase")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Merge duplicate nodes in the knowledge graph"
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        default=True,
        help="Show what would be done without making changes (default)",
    )
    parser.add_argument(
        "--apply", "-a", action="store_true", help="Actually apply the changes"
    )
    parser.add_argument(
        "--simple",
        "-s",
        action="store_true",
        help="Just rename to lowercase without merging (use if APOC not installed)",
    )

    args = parser.parse_args()

    dry_run = not args.apply

    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print("   Use --apply to actually make changes")
    else:
        print("⚠️  APPLYING CHANGES - This will modify the database")
        confirm = input("Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    print()

    if args.simple:
        simple_lowercase_rename(dry_run=dry_run)
    else:
        merge_duplicates(dry_run=dry_run)
