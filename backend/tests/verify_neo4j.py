"""
Neo4j Verification Script
Checks that all notes and graph structures were properly ingested.
"""

from app.services.graph import graph_service
from app.core.logging_config import get_component_logger

logger = get_component_logger("Neo4jVerification")


def verify_neo4j():
    """Comprehensive Neo4j verification after bulk ingestion."""

    print("\n" + "=" * 80)
    print("NEO4J VERIFICATION REPORT")
    print("=" * 80 + "\n")

    # 1. Count all Notes
    print("📝 NOTES")
    print("-" * 80)
    notes_query = """
    MATCH (n:Note)
    RETURN count(n) as total_notes,
           count(n.domain) as notes_with_domain,
           count(n.embedding) as notes_with_embedding,
           count(n.title) as notes_with_title
    """
    result = graph_service.execute_query(notes_query)
    if result:
        r = result[0]
        print(f"Total Notes: {r['total_notes']}")
        print(f"Notes with Domain: {r['notes_with_domain']}")
        print(f"Notes with Embedding: {r['notes_with_embedding']}")
        print(f"Notes with Title: {r['notes_with_title']}")

    # 2. Domain Distribution
    print("\n📊 DOMAIN DISTRIBUTION")
    print("-" * 80)
    domain_query = """
    MATCH (n:Note)
    WHERE n.domain IS NOT NULL
    RETURN n.domain as domain, count(*) as count
    ORDER BY count DESC
    """
    domain_results = graph_service.execute_query(domain_query)
    if domain_results:
        for row in domain_results:
            print(f"{row['domain']}: {row['count']} notes")
    else:
        print("⚠️  No domains found!")

    # 3. Count Knowledge Graph Nodes
    print("\n🧠 KNOWLEDGE GRAPH NODES")
    print("-" * 80)
    node_types = ["Concept", "Entity", "Task", "Persona", "Reference"]
    for node_type in node_types:
        query = f"""
        MATCH (n:{node_type})
        RETURN count(n) as count
        """
        result = graph_service.execute_query(query)
        if result:
            count = result[0]["count"]
            print(f"{node_type}s: {count}")

    # 4. Check Indexable nodes (should match sum of above)
    print("\n🔍 INDEXABLE NODES (Unified Vector Index)")
    print("-" * 80)
    indexable_query = """
    MATCH (n:Indexable)
    RETURN labels(n) as labels, count(*) as count
    ORDER BY count DESC
    """
    indexable_results = graph_service.execute_query(indexable_query)
    total_indexable = 0
    if indexable_results:
        for row in indexable_results:
            # Filter out 'Indexable' from labels to show the actual type
            actual_labels = [l for l in row["labels"] if l != "Indexable"]
            label_str = ", ".join(actual_labels)
            print(f"{label_str}: {row['count']}")
            total_indexable += row["count"]
        print(f"\nTotal Indexable Nodes: {total_indexable}")

    # 5. Check Relationships
    print("\n🔗 RELATIONSHIPS")
    print("-" * 80)
    rel_types = ["MENTIONS", "CONTRIBUTES_TO", "PRODUCES_TASK", "REVEALED_BY"]
    for rel_type in rel_types:
        query = f"""
        MATCH ()-[r:{rel_type}]->()
        WHERE r.is_active = true
        RETURN count(r) as count
        """
        result = graph_service.execute_query(query)
        if result:
            count = result[0]["count"]
            print(f"{rel_type}: {count} active relationships")

    # 6. Sample Recent Notes
    print("\n📅 RECENT NOTES (Last 5)")
    print("-" * 80)
    recent_query = """
    MATCH (n:Note)
    RETURN n.id as id, 
           n.title as title, 
           n.domain as domain,
           n.created_at as created_at
    ORDER BY n.created_at DESC
    LIMIT 5
    """
    recent_results = graph_service.execute_query(recent_query)
    if recent_results:
        for row in recent_results:
            title = row.get("title", "Untitled")[:50]
            domain = row.get("domain", "Unknown")
            created = row.get("created_at", "Unknown")
            print(f"  • {title} ({domain}) - {created}")

    # 7. Check for orphaned notes (notes with no relationships)
    print("\n⚠️  ORPHANED NOTES (No Graph Connections)")
    print("-" * 80)
    orphan_query = """
    MATCH (n:Note)
    WHERE NOT (n)--()
    RETURN count(n) as orphan_count
    """
    result = graph_service.execute_query(orphan_query)
    if result:
        orphan_count = result[0]["orphan_count"]
        print(f"Orphaned Notes: {orphan_count}")
        if orphan_count > 0:
            print("  (These notes exist but have no extracted knowledge)")

    # 8. Vector Index Health Check
    print("\n🎯 VECTOR INDEX HEALTH")
    print("-" * 80)
    try:
        # Check note vector index
        note_index_query = """
        SHOW INDEXES
        YIELD name, type, entityType, labelsOrTypes, properties
        WHERE name = 'note_vector_index'
        RETURN name, type, entityType, labelsOrTypes, properties
        """
        result = graph_service.execute_query(note_index_query)
        if result:
            print("✅ note_vector_index exists")
        else:
            print("⚠️  note_vector_index not found")

        # Check distilled knowledge index
        distilled_index_query = """
        SHOW INDEXES
        YIELD name, type, entityType, labelsOrTypes, properties
        WHERE name = 'distilled_knowledge_index'
        RETURN name, type, entityType, labelsOrTypes, properties
        """
        result = graph_service.execute_query(distilled_index_query)
        if result:
            print("✅ distilled_knowledge_index exists")
        else:
            print("⚠️  distilled_knowledge_index not found")

    except Exception as e:
        print(f"⚠️  Could not verify vector indexes: {e}")

    # 9. Sample Graph Structure (pick one note and show its connections)
    print("\n🌐 SAMPLE GRAPH STRUCTURE")
    print("-" * 80)
    sample_query = """
    MATCH (n:Note)
    WHERE EXISTS((n)--())
    WITH n LIMIT 1
    OPTIONAL MATCH (n)-[r:CONTRIBUTES_TO]->(c:Concept)
    OPTIONAL MATCH (n)-[r2:MENTIONS]->(e:Entity)
    OPTIONAL MATCH (n)-[r3:PRODUCES_TASK]->(t:Task)
    RETURN n.title as note_title,
           collect(DISTINCT c.name) as concepts,
           collect(DISTINCT e.name) as entities,
           collect(DISTINCT t.description) as tasks
    """
    result = graph_service.execute_query(sample_query)
    if result and result[0]:
        row = result[0]
        print(f"Note: {row['note_title'][:60] if row['note_title'] else 'Untitled'}")
        if row["concepts"] and row["concepts"][0]:
            print(f"  Concepts: {', '.join([c for c in row['concepts'] if c][:3])}")
        if row["entities"] and row["entities"][0]:
            print(f"  Entities: {', '.join([e for e in row['entities'] if e][:3])}")
        if row["tasks"] and row["tasks"][0]:
            print(f"  Tasks: {', '.join([t for t in row['tasks'] if t][:2])}")

    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    verify_neo4j()
