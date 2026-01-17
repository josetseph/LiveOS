from app.services.embedding import embedding_service
from app.services.graph import graph_service
import uuid

def test_mrl():
    text = "The quick brown fox jumps over the lazy dog."
    print("Generating Embedding (4096 dims)...")
    full_vector = embedding_service.embed_query(text)
    print(f"Original Dimension: {len(full_vector)}")

    # MRL Truncation
    print("Truncating to 2048 dims...")
    truncated_vector = full_vector[:2048]
    print(f"New Dimension: {len(truncated_vector)}")

    # Insert
    print("Inserting into Neo4j...")
    note_id = str(uuid.uuid4())
    graph_service.execute_query(
        "CREATE (n:Note {id: $id, content: $content, embedding: $vector})",
        {"id": note_id, "content": text, "vector": truncated_vector}
    )

    # Search
    print("Searching...")
    # We query using the SAME truncation
    results = graph_service.query_vector(truncated_vector, top_k=1)
    print("Search Result:", results)
    
    if results and results[0]['id'] == note_id:
        print("MRL VERIFIED: Successfully stored and retrieved truncated vector.")
    else:
        print("MRL FAILED: Could not retrieve info (or ID mismatch).")

if __name__ == "__main__":
    test_mrl()
