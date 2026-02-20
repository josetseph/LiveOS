#!/usr/bin/env python3
"""
Check what properties Entity nodes actually have
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import graph_service


def main():
    # Check properties on Entity nodes
    query = """
    MATCH (e:Entity)
    WITH e LIMIT 5
    RETURN e.name as name, 
           keys(e) as properties,
           labels(e) as labels
    """

    result = graph_service.execute_query(query, {})

    print("=" * 80)
    print("SAMPLE ENTITY PROPERTIES")
    print("=" * 80 + "\n")

    for entity in result:
        print(f"Entity: {entity['name']}")
        print(f"Labels: {entity['labels']}")
        print(f"Properties: {entity['properties']}")
        print()

    # Check if there's a 'type' property instead of 'entity_type'
    print("=" * 80)
    print("CHECKING FOR TYPE PROPERTY")
    print("=" * 80 + "\n")

    query2 = """
    MATCH (e:Entity)
    WHERE e.summary IS NOT NULL
      AND size(e.summary) > 20
    RETURN e.name as name,
           e.type as type,
           e.entity_type as entity_type,
           size(e.summary) as summary_len
    LIMIT 10
    """

    result2 = graph_service.execute_query(query2, {})

    for entity in result2:
        print(
            f"{entity['name']:20} | type={entity.get('type'):15} | entity_type={entity.get('entity_type'):15} | summary_len={entity.get('summary_len')}"
        )

    # Count how many have each
    print("\n" + "=" * 80)
    print("PROPERTY COUNTS")
    print("=" * 80 + "\n")

    count_queries = [
        (
            "Has 'type' property",
            "MATCH (e:Entity) WHERE e.type IS NOT NULL RETURN count(e) as cnt",
        ),
        (
            "Has 'entity_type' property",
            "MATCH (e:Entity) WHERE e.entity_type IS NOT NULL RETURN count(e) as cnt",
        ),
        (
            "Has neither",
            "MATCH (e:Entity) WHERE e.type IS NULL AND e.entity_type IS NULL RETURN count(e) as cnt",
        ),
    ]

    for label, q in count_queries:
        result = graph_service.execute_query(q, {})
        count = result[0]["cnt"] if result else 0
        print(f"{label:30} {count}")

    print()


if __name__ == "__main__":
    main()
