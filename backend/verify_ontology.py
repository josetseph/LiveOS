from app.services.graph import graph_service

def verify_ontology():
    print("--- Graph Verification ---")
    
    # Check Notes
    notes = graph_service.execute_query("MATCH (n:Note) RETURN n.id as id, n.summary as summary, size(n.embedding) as embed_size, n.sentiment as sentiment")
    print(f"Notes found: {len(notes)}")
    for n in notes:
        print(f"  Note {n['id']}: Summary='{n['summary'][:50]}...', EmbedDim={n['embed_size']}, Sentiment={n['sentiment']}")

    # Check Concepts
    concepts = graph_service.execute_query("MATCH (c:Concept) RETURN c.name as name")
    print(f"Concepts found: {len(concepts)}")
    print(f"  Names: {[c['name'] for c in concepts]}")

    # Check Tasks
    tasks = graph_service.execute_query("MATCH (t:Task) RETURN t.description as desc, t.status as status")
    print(f"Tasks found: {len(tasks)}")
    for t in tasks:
        print(f"  Task: {t['desc']} [{t['status']}]")

    # Check Relationships and Metadata (Temporal Edge Logic)
    rels = graph_service.execute_query("MATCH (n:Note)-[r]->(c) RETURN type(r) as rel_type, r.created_at as created_at LIMIT 5")
    print(f"Relationship Samples (Temporal Logic):")
    for r in rels:
        print(f"  -{r['rel_type']}-> at {r['created_at']}")

if __name__ == "__main__":
    verify_ontology()
