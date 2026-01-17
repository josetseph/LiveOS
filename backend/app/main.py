import os
import shutil
import uuid
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="LiveOS Brain API", version="0.1.0")

# Ensure upload directory exists
UPLOAD_DIR = os.path.join(os.getcwd(), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Static file serving for uploads
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# CORS setup used to allow connections from Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file to R2 Cloud Storage.
    """
    from app.utils.bucket_storage import send_files, get_files
    import uuid
    
    # Generate unique key
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    content = await file.read()
    
    # Upload to R2
    await send_files(content, filename, file.content_type)
    
    # Get Public URL
    url = get_files(filename)
    
    return {
        "filename": file.filename,
        "url": url,
        "local_path": url, # Legacy compatibility
        "status": "success"
    }

@app.get("/")
async def root():
    return {"message": "LiveOS Brain is online", "status": "active"}

@app.get("/health")
async def health_check():
    # TODO: Check Neo4j connection here
    return {"status": "healthy", "neo4j": "unknown"}

from app.schemas.extraction import NoteInput
from app.workflows.ingestion import ingestion_workflow



from pydantic import BaseModel
class ChatInput(BaseModel):
    query: str

from app.workflows.chat import chat_workflow

@app.post("/api/v1/chat")
async def chat(input: ChatInput):
    """
    Chat with your Brain: Vector Search -> Rerank -> Synthesis.
    """
    return await chat_workflow.chat(input.query)

from app.services.graph import graph_service

@app.get("/api/v1/graph/summary")
async def get_graph_summary():
    """
    Fetch top themes (Concepts) and Entities for the sidebar.
    """
    # Simple Cypher to get top concepts
    query = """
    MATCH (c:Concept)
    RETURN c.name as name, c.description as description
    LIMIT 10
    """
    with graph_service.driver.session() as session:
        result = session.run(query)
        concepts = [record.data() for record in result]
    
    return {"themes": concepts}

@app.get("/api/v1/graph/visualization")
async def get_graph_visualization():
    """
    Fetch nodes and edges for 2D Force Graph.
    Now INCLUDES Notes to ensure the graph is populated.
    """
    query = """
    MATCH (n)-[r]->(m)
    RETURN n.name as source_name, labels(n)[0] as source_label, id(n) as source_id,
           m.name as target_name, labels(m)[0] as target_label, id(m) as target_id,
           type(r) as type
    LIMIT 500
    UNION
    MATCH (n:Note)
    RETURN "Note" as source_name, "Note" as source_label, id(n) as source_id,
           n.summary as target_name, "Summary" as target_label, id(n) as target_id,
           "SELF" as type
    LIMIT 100
    """
    # Simplified query to just get all connections including Notes
    query = """
    MATCH (n)-[r]->(m)
    RETURN n.name as source_name, labels(n)[0] as source_label, id(n) as source_id,
           m.name as target_name, labels(m)[0] as target_label, id(m) as target_id,
           type(r) as type
    LIMIT 500
    """
    # Actually, for Notes that might not have connections yet, we might want to just show them?
    # But usually ForceGraph needs links. Let's stick to the original query but REMOVE the Note exclusion.
    # And maybe add a separate match for Notes to ensure they appear even if disconnected (force graph can handle disconnected nodes if we pass them in nodes list).
    
    query = """
    MATCH (n)
    WHERE labels(n)[0] IN ['Note', 'Concept', 'Entity', 'Task']
    OPTIONAL MATCH (n)-[r]->(m)
    RETURN n.id as source_id, n.summary as source_name, labels(n)[0] as source_label,
           m.id as target_id, m.name as target_name, labels(m)[0] as target_label,
           type(r) as type
    LIMIT 300
    """
    
    # Let's use a cleaner query that gets everything.
    query = """
    MATCH (n)-[r]->(m)
    RETURN elementId(n) as source_id, 
           COALESCE(n.name, n.summary, n.content, n.trait, n.description) as source_name, 
           labels(n)[0] as source_label,
           n.id as source_uuid,
           n.summary as source_summary,
           elementId(m) as target_id, 
           COALESCE(m.name, m.summary, m.trait, m.description) as target_name, 
           labels(m)[0] as target_label,
           m.id as target_uuid,
           m.summary as target_summary,
           type(r) as type
    
    UNION
    MATCH (n:Note)
    WHERE NOT (n)--()
    RETURN elementId(n) as source_id, 
           COALESCE(n.name, n.summary, n.content, n.trait, n.description) as source_name, 
           labels(n)[0] as source_label,
           n.id as source_uuid,
           n.summary as source_summary,
           NULL as target_id, 
           NULL as target_name, 
           NULL as target_label,
           NULL as target_uuid,
           NULL as target_summary,
           NULL as type
    
    """
    
    nodes = {}
    links = []
    
    with graph_service.driver.session() as session:
        result = session.run(query)
        for record in result:
            s_id = str(record["source_id"])
            
            # Skip if source has no useful label
            if not record["source_label"]: continue

            name = record["source_name"]
            if name and len(name) > 30: name = name[:30] + "..."
            
            if s_id not in nodes:
                nodes[s_id] = {
                    "id": s_id, 
                    "name": name or "Untitled", 
                    "group": record["source_label"],
                    "uuid": record["source_uuid"],
                    "summary": record["source_summary"]
                }
            
            if record["target_id"] is not None:
                t_id = str(record["target_id"])
                t_name = record["target_name"]
                if t_name and len(t_name) > 30: t_name = t_name[:30] + "..."
                
                if t_id not in nodes:
                    nodes[t_id] = {
                        "id": t_id, 
                        "name": t_name or "Untitled", 
                        "group": record["target_label"],
                        "uuid": record["target_uuid"],
                        "summary": record["target_summary"]
                    }
                
                links.append({"source": s_id, "target": t_id, "type": record["type"]})
            
    return {"nodes": list(nodes.values()), "links": links}

# --- Notes API ---

from app.core.database import get_db
from app.models.note import Note
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from fastapi import Depends, HTTPException

class NoteResponse(BaseModel):
    id: str
    content: str
    created_at: str | None = None
    title: str | None = None
    summary: str | None = None

    class Config:
        from_attributes = True

@app.post("/api/v1/ingest")
async def ingest_note(note_data: NoteInput, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Ingest a new note: 
    1. Save to Postgres (Body).
    2. Background: Extract metadata -> Save to Graph (Mind).
    """
    note_id = str(uuid.uuid4())
    
    # 1. Save to Postgres
    # Use provided created_at if available (for historical notes), else default to now.
    # We parse the ISO string if provided.
    c_at = datetime.utcnow()
    if note_data.created_at:
        try:
             # Try parsing common formats if not strict ISO
             import dateparser
             dt = dateparser.parse(note_data.created_at)
             if dt: c_at = dt
        except:
             pass # Fallback to now

    new_note = Note(
        id=note_id,
        content=note_data.content,
        created_at=c_at
    )
    db.add(new_note)
    await db.commit()
    
    # 2. Trigger Graph Ingestion
    # Pass created_at along so the agent knows about it too
    if note_data.created_at is None:
        note_data.created_at = c_at.isoformat()
        
    background_tasks.add_task(ingestion_workflow.process_note, note_data, note_id)
    
    return {
        "note_id": note_id,
        "status": "processing_started",
        "content": note_data.content,
        "created_at": c_at.isoformat()
    }

@app.get("/api/v1/notes")
async def get_notes(search: str | None = None, db: AsyncSession = Depends(get_db)):
    """
    Get all notes sorted by creation date (newest first).
    """
    if search:
        term = f"%{search}%"
        query = select(Note).where(
            (Note.title.ilike(term)) | (Note.content.ilike(term))
        ).order_by(Note.created_at.desc()).limit(100)
    else:
        query = select(Note).order_by(Note.created_at.desc()).limit(100)

    result = await db.execute(query)
    notes = result.scalars().all()
    # Normalize created_at to string for JSON serialization if needed, or rely on Pydantic
    return notes

@app.get("/api/v1/notes/{note_id}")
async def get_note(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get a specific note by ID from Postgres.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    
    if not note:
        return {"error": "Note not found"}
    return note

@app.put("/api/v1/notes/{note_id}")
async def update_note(note_id: str, note_data: NoteInput, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Update a note:
    1. Check if content changed.
    2. If changed => Update Postgres (processed=False) -> Trigger Background Ingestion.
    3. If same => Do nothing.
    """
    # 1. Fetch existing note to compare
    result = await db.execute(select(Note).where(Note.id == note_id))
    existing_note = result.scalar_one_or_none()
    
    if not existing_note:
        return {"error": "Note not found", "status": "failed"}

    # 2. Idempotency Check
    if existing_note.content == note_data.content:
        # If content is identical and it's already processed, skip.
        # If it's identical but somehow processed=False (failed prev run?), we might want to re-run.
        # For strict user requirement: "If exactly the same, nothing happens."
        if existing_note.processed:
            return {"status": "skipped_no_change", "id": note_id}
        
        # If processed=False, we fall through to trigger ingestion again (retry)
    
    # 3. Update Postgres
    # Reset processed = False because we are changing it
    existing_note.content = note_data.content
    existing_note.processed = False
    
    # Update created_at if provided (for correcting dates)
    if note_data.created_at:
        try:
             import dateparser
             dt = dateparser.parse(note_data.created_at)
             if dt: existing_note.created_at = dt
        except:
             pass

    # updated_at will auto-update if config allows, or we set it manually:
    existing_note.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(existing_note)

    # 4. Trigger Re-Ingestion (Background)
    background_tasks.add_task(ingestion_workflow.process_note, note_data, note_id)
    
    return {"status": "updated_and_processing", "id": note_id}

@app.delete("/api/v1/notes/{note_id}")
async def delete_note(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a note from Postgres AND Neo4j.
    """
    # 1. Delete from Postgres
    await db.execute(delete(Note).where(Note.id == note_id))
    await db.commit()
    
    # 2. Delete from Bio/Graph (Neo4j)
    # We can do this synchronously here as it's fast enough, or background it.
    query = """
    MATCH (n:Note {id: $id})
    DETACH DELETE n
    """
    with graph_service.driver.session() as session:
        session.run(query, {"id": note_id})
    
    return {"status": "deleted", "id": note_id}
