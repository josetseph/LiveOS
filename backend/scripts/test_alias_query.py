#!/usr/bin/env python3
"""
Test the exact query used in show_alias_candidates
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import graph_service


def main():
    # Test the exact query from show_alias_candidates
    entity_type = None  # User didn't specify --type
    limit = 100  # Default

    type_filter = f"{{entity_type: '{entity_type}'}}" if entity_type else ""
    query = f"""
    MATCH (e:Entity {type_filter})
    WHERE NOT (e)-[:IS_SAME_AS]->()
      AND e.summary IS NOT NULL
      AND size(e.summary) > 20
    RETURN e.name as name, e.entity_type as type, e.summary as summary
    LIMIT $limit
    """

    print("Query to execute:")
    print(query)
    print(f"\nParams: {{limit: {limit}}}")
    print("\n" + "=" * 80 + "\n")

    try:
        entities = graph_service.execute_query(query, {"limit": limit})
        print(f"✅ Query succeeded!")
        print(f"   Returned {len(entities)} entities\n")

        if entities:
            print("Sample results:")
            for i, e in enumerate(entities[:5], 1):
                print(
                    f"   {i}. {e['name']} ({e['type']}) - summary length: {len(e['summary'])}"
                )
        else:
            print("❌ Query returned empty list!")
            print("\nTrying simplified query...")

            # Try without the NOT clause
            simple_query = """
            MATCH (e:Entity)
            WHERE e.summary IS NOT NULL
              AND size(e.summary) > 20
            RETURN e.name as name, e.entity_type as type, e.summary as summary
            LIMIT $limit
            """
            entities2 = graph_service.execute_query(simple_query, {"limit": limit})
            print(f"   Without IS_SAME_AS check: {len(entities2)} entities")

    except Exception as e:
        print(f"❌ Query failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
