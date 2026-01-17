from app.workflows.ingestion import ingestion_workflow
from app.schemas.extraction import NoteInput
from app.services.graph import graph_service

def report():
    print("\n--- Current Concept Summaries ---")
    summaries = graph_service.execute_query("MATCH (c:Concept) RETURN c.name as name, c.summary as summary")
    if not summaries:
        print("No concepts found in Neo4j.")
    for s in summaries:
        print(f"Concept: {s['name']} | Summary: {s['summary']}")

def test_delta_updates():
    print("--- Delta Update Verification ---")
    
    # 1. Clear Graph
    print("Clearing Graph...")
    graph_service.execute_query("MATCH (n) DETACH DELETE n")

    # 2. First Note: Sick
    print("\n[Step 1] User is sick...")
    note1 = NoteInput(content="My Health is not great today. I've been feeling quite ill lately with a heavy cold and coughing.")
    res1 = ingestion_workflow.process_note(note1)
    print(f"Ingestion Result: {res1['status']}")
    report()

    # 3. Second Note: Recovery (The Delta)
    print("\n[Step 2] User is healthy now...")
    note2 = NoteInput(content="Woke up feeling 100% better! Regarding my Health, the cold is gone and I have my energy back.")
    res2 = ingestion_workflow.process_note(note2)
    print(f"Ingestion Result: {res2['status']}")
    report()

if __name__ == "__main__":
    test_delta_updates()
