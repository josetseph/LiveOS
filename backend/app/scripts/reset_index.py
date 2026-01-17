from app.services.graph import graph_service
from app.scripts.init_db import init_db

def reset_index():
    print("Dropping existing vector index...")
    try:
        # Syntax for dropping index in Neo4j 5.x
        graph_service.execute_query("DROP INDEX note_vector_index IF EXISTS")
        print("Index dropped.")
    except Exception as e:
        print(f"Error dropping index: {e}")

    print("Re-initializing database (Recreating Index)...")
    init_db()

if __name__ == "__main__":
    reset_index()
