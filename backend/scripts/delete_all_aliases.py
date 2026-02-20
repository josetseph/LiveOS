#!/usr/bin/env python3
"""
Delete all IS_SAME_AS relationships from the graph.

This is useful when you need to start fresh with alias detection
after improving the algorithm or fixing false positives.

Usage:
    python scripts/delete_all_aliases.py              # Interactive confirmation
    python scripts/delete_all_aliases.py --yes        # Skip confirmation
"""

import sys
import os
import argparse

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import GraphService


def count_alias_links():
    """Count total IS_SAME_AS relationships."""
    query = """
    MATCH ()-[r:IS_SAME_AS]->()
    RETURN COUNT(r) as total
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query)
    return result[0]["total"] if result else 0


def delete_all_alias_links():
    """Delete all IS_SAME_AS relationships."""
    query = """
    MATCH ()-[r:IS_SAME_AS]->()
    DELETE r
    RETURN COUNT(r) as deleted
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query)
    return result[0]["deleted"] if result else 0


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Delete all IS_SAME_AS relationships from the graph"
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    print("🗑️  Delete All IS_SAME_AS Relationships")
    print("=" * 80)

    # Count existing links
    print("\nCounting IS_SAME_AS relationships...")
    total = count_alias_links()

    if total == 0:
        print("No IS_SAME_AS relationships found. Nothing to delete.")
        return

    print(f"\n⚠️  Found {total} IS_SAME_AS relationships")
    print("\nThis will permanently delete all alias links from your graph.")
    print(
        "The original nodes will remain - only the IS_SAME_AS relationships will be removed."
    )

    # Confirm deletion
    if not args.yes:
        print("\n" + "=" * 80)
        confirm = input("Type 'DELETE ALL' to confirm: ").strip()

        if confirm != "DELETE ALL":
            print("\n❌ Cancelled. No changes made.")
            return

    # Delete all links
    print("\nDeleting all IS_SAME_AS relationships...")
    deleted = delete_all_alias_links()

    print(f"\n✅ Successfully deleted {deleted} IS_SAME_AS relationships")
    print("\nYour graph is now clean and ready for improved alias detection.")


if __name__ == "__main__":
    main()
