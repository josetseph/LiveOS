#!/usr/bin/env python3
"""
Migrate existing alias/relationship links to add missing properties.

This script adds is_active, confidence, and context properties to existing
IS_SAME_AS, IS_VARIANT_OF, IS_SIMILAR_TO, and RELATED_TO relationships
that were created before the property standardization.

Usage:
    python scripts/migrate_relationship_properties.py              # Interactive confirmation
    python scripts/migrate_relationship_properties.py --yes        # Skip confirmation
"""

import sys
import os
import argparse

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import GraphService


def count_relationships_needing_migration():
    """Count relationships missing the new properties."""
    query = """
    MATCH ()-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-()
    WHERE r.is_active IS NULL
    RETURN type(r) as rel_type, COUNT(r) as count
    ORDER BY rel_type
    """

    graph_service = GraphService()
    results = graph_service.execute_query(query)
    return results


def migrate_relationships():
    """
    Add missing properties to existing relationships.

    Maps relationship types to confidence scores:
    - IS_SAME_AS: 1.0 (certain - exact same entity)
    - IS_VARIANT_OF: 0.7 (likely same but ambiguous)
    - IS_SIMILAR_TO: 0.6 (different but closely related)
    - RELATED_TO: 0.5 (different but connected)
    """
    query = """
    MATCH ()-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-()
    WHERE r.is_active IS NULL
    WITH r, type(r) as rel_type
    SET r.is_active = true,
        r.confidence = CASE type(r)
            WHEN 'IS_SAME_AS' THEN 1.0
            WHEN 'IS_VARIANT_OF' THEN 0.7
            WHEN 'IS_SIMILAR_TO' THEN 0.6
            WHEN 'RELATED_TO' THEN 0.5
            ELSE 0.5
        END,
        r.context = coalesce(r.reason, 'Relationship detected by alias detector')
    RETURN type(r) as rel_type, COUNT(r) as updated
    """

    graph_service = GraphService()
    results = graph_service.execute_query(query)
    return results


def verify_migration():
    """Verify all relationships now have the required properties."""
    query = """
    MATCH ()-[r:IS_SAME_AS|IS_VARIANT_OF|IS_SIMILAR_TO|RELATED_TO]-()
    WHERE r.is_active IS NULL OR r.confidence IS NULL OR r.context IS NULL
    RETURN COUNT(r) as incomplete_count
    """

    graph_service = GraphService()
    result = graph_service.execute_query(query)
    return result[0]["incomplete_count"] if result else 0


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Migrate existing alias relationships to add missing properties"
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    print("🔧 Relationship Property Migration")
    print("=" * 80)

    # Count relationships needing migration
    print("\nChecking for relationships needing migration...")
    needs_migration = count_relationships_needing_migration()

    if not needs_migration:
        print("✅ All relationships already have the required properties!")
        return

    print(f"\n📊 Found relationships needing migration:")
    total = 0
    for record in needs_migration:
        count = record["count"]
        total += count
        print(f"   {record['rel_type']}: {count} relationships")

    print(f"\n   Total: {total} relationships")

    print("\n📝 Will add the following properties:")
    print("   • is_active: true")
    print("   • confidence: (based on relationship type)")
    print("     - IS_SAME_AS: 1.0 (certain)")
    print("     - IS_VARIANT_OF: 0.7 (likely)")
    print("     - IS_SIMILAR_TO: 0.6 (related)")
    print("     - RELATED_TO: 0.5 (connected)")
    print("   • context: (reuse existing 'reason' field)")

    # Confirm migration
    if not args.yes:
        print("\n" + "=" * 80)
        confirm = input("Proceed with migration? [y/N]: ").strip()

        if confirm.lower() != "y":
            print("\n❌ Migration cancelled")
            return

    # Run migration
    print("\n🚀 Running migration...")
    results = migrate_relationships()

    if results:
        print("\n✅ Migration complete:")
        for record in results:
            print(f"   {record['rel_type']}: {record['updated']} relationships updated")

    # Verify
    print("\n🔍 Verifying migration...")
    incomplete = verify_migration()

    if incomplete == 0:
        print("✅ All relationships now have complete properties!")
    else:
        print(f"⚠️  Warning: {incomplete} relationships still incomplete")

    print("\n" + "=" * 80)
    print("Migration complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
