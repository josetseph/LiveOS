#!/usr/bin/env python
"""Debug script to check Note-Entity relationships for references."""

from app.services.graph import graph_service

# Check if we have any relationships between Notes and Entities
query = """
MATCH (note:Note)-[r]->(n:Indexable)
WHERE type(r) IN ['MENTIONS', 'CONTRIBUTES_TO', 'PRODUCES_TASK', 'REVEALED_BY']
RETURN type(r) as rel_type, count(*) as count
"""
result = graph_service.execute_query(query)
print("Relationship counts:")
for r in result:
    print(f"  {r['rel_type']}: {r['count']}")

# Test get_linked_evidence directly with both cases
print("\n\nTesting get_linked_evidence (case sensitivity test):")
test_names = ["Svtlottery", "svtlottery", "Ceruba", "ceruba", "Finances", "finances"]
evidence = graph_service.get_linked_evidence(test_names, limit_per_node=2)
for row in evidence:
    print(f"  {row.get('node_name')}: {len(row.get('evidence', []))} notes")
    for note in row.get("evidence", []):
        print(f"    - {note.get('id')}: {note.get('title')}")
