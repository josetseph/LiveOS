#!/usr/bin/env python
"""Check Neo4j graph state"""
from app.services.graph import graph_service

# Check nodes
print("=== NODES ===")
nodes = graph_service.execute_query(
    """
    MATCH (n) WHERE n:Entity OR n:Concept OR n:Task
    RETURN labels(n) as labels, n.name as name, n.summary as summary
    LIMIT 10
"""
)
for n in nodes:
    summary = n.get("summary") or "NONE"
    print(f"  {n['labels']}: {n['name']}")
    print(f"    Summary: {summary[:80]}...")

# Check relationships
print("\n=== RELATIONSHIPS ===")
rels = graph_service.execute_query(
    """
    MATCH (note:Note)-[r]->(n)
    WHERE n:Entity OR n:Concept OR n:Task
    RETURN type(r) as rel_type, r.is_active as is_active, 
           note.id as note_id, n.name as node_name
    LIMIT 10
"""
)
for r in rels:
    print(
        f"  {r['rel_type']} (active={r['is_active']}): Note {r['note_id'][:8]}... -> {r['node_name']}"
    )

# Check Indexable label
print("\n=== INDEXABLE COUNT ===")
indexable = graph_service.execute_query("MATCH (n:Indexable) RETURN count(n) as count")
print(f"  Count: {indexable[0]['count']}")

# Test get_linked_evidence directly
print("\n=== TEST get_linked_evidence ===")
node_names = [
    "ceruba",
    "svtlottery",
    "complete #ceruba",
    "complete #svtlottery",
    "lonely",
    "problems",
    "empty",
]
evidence = graph_service.get_linked_evidence(node_names, limit_per_node=2)
print(f"  Results: {len(evidence)}")
for e in evidence:
    print(f"    {e['node_name']}: {len(e['evidence'])} evidence notes")
