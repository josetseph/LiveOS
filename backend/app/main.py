import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Setup logging before any other imports
from app.core.logging_config import setup_logging

setup_logging()

app = FastAPI(title="LiveOS Brain API", version="0.1.0")

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
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    content = await file.read()

    # Upload to R2
    await send_files(content, filename, file.content_type)

    # Get Public URL
    url = get_files(filename)

    return {
        "filename": file.filename,
        "url": url,
        "local_path": url,  # Legacy compatibility
        "status": "success",
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

    # Let's use a cleaner query that gets everything.
    query = """
    MATCH (n)-[r]->(m)
    RETURN elementId(n) as source_id, 
           COALESCE(n.name, n.summary, n.content, n.trait, n.description, n.title) as source_name, 
           labels(n)[0] as source_label,
           n.id as source_uuid,
           n.summary as source_summary,
           n.domain as source_domain,
           elementId(m) as target_id, 
           COALESCE(m.name, m.summary, m.trait, m.description, m.title) as target_name, 
           labels(m)[0] as target_label,
           m.id as target_uuid,
           m.summary as target_summary,
           m.domain as target_domain,
           type(r) as type
    
    UNION
    MATCH (n:Note)
    WHERE NOT (n)--()
    RETURN elementId(n) as source_id, 
           COALESCE(n.name, n.summary, n.content, n.trait, n.description, n.title) as source_name, 
           labels(n)[0] as source_label,
           n.id as source_uuid,
           n.summary as source_summary,
           n.domain as source_domain,
           NULL as target_id, 
           NULL as target_name, 
           NULL as target_label,
           NULL as target_uuid,
           NULL as target_summary,
           NULL as target_domain,
           NULL as type
    
    """

    nodes = {}
    links = []

    with graph_service.driver.session() as session:
        result = session.run(query)
        for record in result:
            s_id = str(record["source_id"])

            # Skip if source has no useful label
            if not record["source_label"]:
                continue

            name = record["source_name"]
            if name and len(name) > 30:
                name = name[:30] + "..."

            if s_id not in nodes:
                nodes[s_id] = {
                    "id": s_id,
                    "name": name or "Untitled",
                    "group": record["source_label"],
                    "uuid": record["source_uuid"],
                    "summary": record["source_summary"],
                    "domain": record["source_domain"],
                }

            if record["target_id"] is not None:
                t_id = str(record["target_id"])
                t_name = record["target_name"]
                if t_name and len(t_name) > 30:
                    t_name = t_name[:30] + "..."

                if t_id not in nodes:
                    nodes[t_id] = {
                        "id": t_id,
                        "name": t_name or "Untitled",
                        "group": record["target_label"],
                        "uuid": record["target_uuid"],
                        "summary": record["target_summary"],
                        "domain": record["target_domain"],
                    }

                links.append({"source": s_id, "target": t_id, "type": record["type"]})

    return {"nodes": list(nodes.values()), "links": links}


@app.get("/api/v1/graph/export")
async def export_graph_for_3d():
    """
    Export full graph data for 3D visualization.
    Returns all nodes (Concepts, Entities, Tasks, Personas, References, Notes)
    and their relationships in 3d-force-graph format.
    """
    graph_data = graph_service.get_full_graph()
    return graph_data


# --- Notes API ---

from app.core.database import get_db
from app.models.note import Note
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import Depends


class NoteResponse(BaseModel):
    id: str
    content: str
    created_at: str | None = None
    title: str | None = None
    summary: str | None = None
    processed: bool = False

    class Config:
        from_attributes = True


class CreateNoteInput(BaseModel):
    content: str
    created_at: str | None = None


@app.post("/api/v1/notes")
async def create_note(
    note_input: CreateNoteInput,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new note in Postgres WITHOUT ingestion.
    Note will have processed=False until explicitly ingested via POST /api/v1/notes/{id}/ingest.
    """
    note_id = str(uuid.uuid4())

    c_at = datetime.now(timezone.utc)
    if note_input.created_at:
        try:
            # Try parsing as ISO format first (from frontend)
            from dateutil import parser as dateutil_parser

            dt = dateutil_parser.isoparse(note_input.created_at)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            c_at = dt
        except:
            # Fallback to dateparser for other formats
            try:
                import dateparser

                dt = dateparser.parse(note_input.created_at)
                if dt:
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    c_at = dt
            except:
                pass

    new_note = Note(
        id=note_id,
        content=note_input.content,
        created_at=c_at,
        processed=False,  # Not ingested yet
    )
    db.add(new_note)
    await db.commit()
    await db.refresh(new_note)

    return new_note


@app.post("/api/v1/notes/{note_id}/ingest")
async def ingest_existing_note(
    note_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger ingestion for an existing note.
    This will process the note in the background and set processed=True when complete.
    """
    # Fetch the note
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()

    if not note:
        return {"error": "Note not found"}, 404

    if note.processed:
        return {
            "note_id": note_id,
            "status": "already_processed",
            "message": "Note has already been ingested",
        }

    # Create NoteInput for the ingestion workflow
    note_data = NoteInput(
        content=note.content,
        created_at=note.created_at.isoformat() if note.created_at else None,
    )

    # Trigger background ingestion
    background_tasks.add_task(ingestion_workflow.process_note, note_data, note_id)

    return {
        "note_id": note_id,
        "status": "processing_started",
        "message": "Note ingestion has been queued",
    }


@app.post("/api/v1/ingest")
async def ingest_note(
    note_data: NoteInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Create and ingest a new note (legacy combined endpoint for batch scripts).
    For manual note creation, prefer POST /api/v1/notes then POST /api/v1/notes/{id}/ingest.
    """
    note_id = str(uuid.uuid4())

    # 1. Save to Postgres
    c_at = datetime.now(timezone.utc)
    if note_data.created_at:
        try:
            import dateparser

            dt = dateparser.parse(note_data.created_at)
            if dt:
                c_at = dt
        except:
            pass

    # Create note with processed=False initially
    new_note = Note(
        id=note_id, content=note_data.content, created_at=c_at, processed=False
    )
    db.add(new_note)
    await db.commit()

    # 2. Trigger ingestion unless skip_ingestion=True
    if not note_data.skip_ingestion:
        if note_data.created_at is None:
            note_data.created_at = c_at.isoformat()
        background_tasks.add_task(ingestion_workflow.process_note, note_data, note_id)
        status = "processing_started"
    else:
        status = "saved_without_ingestion"

    return {
        "note_id": note_id,
        "status": status,
        "content": note_data.content,
        "created_at": c_at.isoformat(),
        "processed": False,  # Will be set to True after background task completes
    }


@app.get("/api/v1/notes")
async def get_notes(
    search: str | None = None,
    processed: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all notes sorted by creation date (newest first).
    Optionally filter by processed status (ingested vs non-ingested).
    """
    base_query = select(Note)

    # Apply filters
    filters = []
    if search:
        term = f"%{search}%"
        filters.append((Note.title.ilike(term)) | (Note.content.ilike(term)))

    if processed is not None:
        filters.append(Note.processed == processed)

    if filters:
        base_query = base_query.where(*filters)

    query = base_query.order_by(Note.created_at.desc())
    result = await db.execute(query)
    notes = result.scalars().all()
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
async def update_note(
    note_id: str,
    note_input: CreateNoteInput,
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing note's content.
    Does NOT trigger re-ingestion or change processed status.
    Use POST /api/v1/notes/{id}/ingest to re-ingest after updating.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    existing_note = result.scalar_one_or_none()

    if not existing_note:
        return {"error": "Note not found"}

    # Update content only, preserve processed status
    existing_note.content = note_input.content

    # Update created_at if provided
    if note_input.created_at:
        try:
            # Try parsing as ISO format first (from frontend)
            from dateutil import parser as dateutil_parser

            dt = dateutil_parser.isoparse(note_input.created_at)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            existing_note.created_at = dt
        except:
            # Fallback to dateparser for other formats
            try:
                import dateparser

                dt = dateparser.parse(note_input.created_at)
                if dt:
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    existing_note.created_at = dt
            except:
                pass

    existing_note.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(existing_note)

    return existing_note


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
