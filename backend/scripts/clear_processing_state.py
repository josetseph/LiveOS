#!/usr/bin/env python3
"""
Clear alias detection processing state.

This script removes the alias_detection_processed_at timestamp from nodes,
allowing them to be reprocessed by the detection script.

Usage:
    python scripts/clear_processing_state.py              # Interactive confirmation
    python scripts/clear_processing_state.py --yes        # Skip confirmation
    python scripts/clear_processing_state.py --label Entity --type Person  # Clear specific type
"""

import sys
import os
import argparse

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import GraphService


def count_processed_nodes(label: str = "Entity", entity_type: str = None):
    """Count nodes with processing state."""
    type_filter = (
        f"{{type: '{entity_type}'}}" if entity_type and label == "Entity" else ""
    )

    query = f"""
    MATCH (n:{label} {type_filter})
    WHERE n.alias_detection_processed_at IS NOT NULL
    RETURN count(n) as total
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query)
    return result[0]["total"] if result else 0


def clear_processing_state(label: str = "Entity", entity_type: str = None):
    """Clear processing state from nodes."""
    type_filter = (
        f"{{type: '{entity_type}'}}" if entity_type and label == "Entity" else ""
    )

    query = f"""
    MATCH (n:{label} {type_filter})
    WHERE n.alias_detection_processed_at IS NOT NULL
    REMOVE n.alias_detection_processed_at
    RETURN count(n) as cleared
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query)
    return result[0]["cleared"] if result else 0


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Clear alias detection processing state to allow reprocessing"
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--label",
        type=str,
        default="Entity",
        choices=["Entity", "Concept", "Task", "Persona", "Reference"],
        help="Node label to clear (default: Entity)",
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="For Entity label only: filter by type (e.g., Person, Place)",
    )
    args = parser.parse_args()

    print("🔄 Clear Alias Detection Processing State")
    print("=" * 80)

    # Count processed nodes
    print(f"\nChecking {args.label} nodes...")
    if args.type:
        print(f"  Type filter: {args.type}")

    total = count_processed_nodes(args.label, args.type)

    if total == 0:
        print(f"\n✅ No processed {args.label} nodes found. Nothing to clear.")
        return

    print(f"\n📊 Found {total} processed {args.label} nodes")
    if args.type:
        print(f"    (type: {args.type})")

    print("\n⚠️  This will remove the alias_detection_processed_at timestamp.")
    print("    These nodes will be reprocessed on the next detection run.")

    # Confirm
    if not args.yes:
        print("\n" + "=" * 80)
        confirm = input("Clear processing state? [y/N]: ").strip()

        if confirm.lower() != "y":
            print("\n❌ Cancelled")
            return

    # Clear state
    print("\n🚀 Clearing processing state...")
    cleared = clear_processing_state(args.label, args.type)

    print(f"\n✅ Cleared processing state from {cleared} nodes")
    print("\n" + "=" * 80)
    print("Next Steps:")
    print("  Run detection script to reprocess these nodes:")
    if args.type:
        print(f"    python scripts/detect_aliases.py --type {args.type}")
    else:
        print(f"    python scripts/detect_aliases.py")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
