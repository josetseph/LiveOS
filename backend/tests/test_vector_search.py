from app.services.embedding import embedding_service
from app.services.graph import graph_service

# Embed the query
query = "Who am I?"
vector = embedding_service.embed_query(query)

print(f"Query: '{query}'")
print(f"Vector size: {len(vector)}")

# Try vector search WITHOUT min_score filter
result = graph_service.execute_query(
    """
CALL db.index.vector.queryNodes('note_vector_index', 10, $vector)
YIELD node, score
RETURN node.id as id, score
ORDER BY score DESC
LIMIT 10
""",
    {"vector": vector},
)

print(f"\nTop 10 results (no score filter):")
for r in result:
    print(f"  Score: {r['score']:.4f} - Note: {r['id'][:8]}...")

# Now with min_score=0.7
result_filtered = graph_service.execute_query(
    """
CALL db.index.vector.queryNodes('note_vector_index', 10, $vector)
YIELD node, score
WHERE score >= 0.7
RETURN node.id as id, score
ORDER BY score DESC
""",
    {"vector": vector},
)

print(f"\nWith min_score >= 0.7:")
print(f"  Found: {len(result_filtered)} results")
