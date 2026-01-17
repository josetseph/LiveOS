from app.services.graph import graph_service
from app.services.embedding import embedding_service
import sys

def reset_index_mrl():
    print("Dropping existing vector index...")
    try:
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
        print("Index dropped.")
    except Exception as e:
        print(f"Error dropping index: {e}")

    print("Creating Vector Index (4096 dimensions)...")
    try:
        query_index = """
        CREATE VECTOR INDEX note_vector_index IF NOT EXISTS
        FOR (n:Note)
        ON (n.embedding)
        OPTIONS {indexConfig: {
         `vector.dimensions`: 4096,
         `vector.similarity_function`: 'cosine'
        }}
        """
        graph_service.execute_query(query_index)
        print("Vector Index 'note_vector_index' created with 4096 dims.")
    except Exception as e:
        print(f"Error creating vector index: {e}")

if __name__ == "__main__":
    reset_index_mrl()
