from app.workflows.ingestion import ingestion_workflow
from app.schemas.extraction import NoteInput
import sys

# User's specific test content
note_text = """
I think I’m failing myself, that’s why I’m feeling this way. I’m not waking up when I should and everything else. I might have to fix my sleeping schedule once more if I hope to have things return to normal. Perhaps.
So far I’ve been able to clean every other day, my room and the two halls.
"""

def run_test():
    print(f"Testing Ingestion with note: '{note_text[:50]}...'")
    
    try:
        # Full flow
        print("Running Full Ingestion (Graph Write)...")
        note_input = NoteInput(content=note_text)
        result = ingestion_workflow.process_note(note_input)
        print("Ingestion Success!")
        print(f"Summary: {result['extraction']['summary']}")
        print(f"Concepts: {[c['name'] for c in result['extraction']['concepts']]}")
        print(f"Tasks: {[t['description'] for t in result['extraction']['tasks']]}")

    except Exception as e:
        print(f"Test Failed: {e}")

if __name__ == "__main__":
    run_test()
