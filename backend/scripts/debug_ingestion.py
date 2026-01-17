
import sys
import os
import traceback
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.workflows.ingestion import ingestion_workflow
from app.schemas.extraction import NoteInput

try:
    print("🚀 Starting Debug Ingestion...")
    note = NoteInput(content="I absolutely love hiking in Yosemite. The granite cliffs make me feel so small.")
    result = ingestion_workflow.process_note(note)
    print("✅ Success:", result)
except Exception:
    traceback.print_exc()
