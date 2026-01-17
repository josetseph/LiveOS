import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.graph import graph_service

def cleanup_graph():
    print("🧹 Cleaning up Graph...")
    
    # query to delete nodes with name 'Untitled', 'unknown', or empty
    query = """
    MATCH (n)
    WHERE (n:Entity OR n:Concept) AND 
          (toLower(n.name) IN ['untitled', 'unknown', 'none', ''] OR n.name IS NULL)
    DETACH DELETE n
    RETURN count(n) as deleted_count
    """
    
    with graph_service.driver.session() as session:
        result = session.run(query)
        count = result.single()['deleted_count']
        
    print(f"✅ Deleted {count} 'Untitled/Garbage' nodes.")

if __name__ == "__main__":
    cleanup_graph()
