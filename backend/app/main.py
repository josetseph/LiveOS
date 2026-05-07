import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

# Setup logging before any other imports
from app.core.log import get_logger, setup_logging
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

setup_logging()
logger = get_logger("API")  # App logger; avoid uvicorn.access formatter expectations

# ---------------------------------------------------------------------------
# Request trace-ID context variable
# ---------------------------------------------------------------------------

# Stores the current request's trace_id for the duration of a request.
# Use `request_trace_id.get()` in any async context to retrieve it.
request_trace_id: ContextVar[str] = ContextVar("request_trace_id", default="")


app = FastAPI(title="LiveOS Brain API", version="0.1.0")

# CORS setup used to allow connections from Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Attach a trace_id to every inbound request.

    The trace_id is:
      1. Read from the incoming X-Request-Id header if provided by the caller.
      2. Generated as a new UUID4 otherwise.

    The value is stored in a ContextVar so any logger that reads it can attach
    it to structured log records without explicit passing. It is also returned
    in the X-Request-Id response header so callers can correlate server-side
    logs with their own traces.
    """
    trace_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    token = request_trace_id.set(trace_id)
    try:
        response: Response = await call_next(request)
    finally:
        request_trace_id.reset(token)
    response.headers["X-Request-Id"] = trace_id
    return response


@app.on_event("startup")
async def startup_event():
    logger.info("Application startup: LiveOS Brain API online")


@app.post("/api/v1/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file to R2 Cloud Storage.
    """
    from app.utils.bucket_storage import get_files, send_files

    logger.info(f"Uploading file: {file.filename}")

    # Generate unique key
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    content = await file.read()

    # Upload to R2
    await send_files(content, filename, file.content_type)

    # Get Public URL
    url = get_files(filename)

    logger.info(f"File uploaded successfully: {filename} -> {url}")

    return {
        "filename": file.filename,
        "url": url,
        "local_path": url,  # Legacy compatibility
        "status": "success",
    }


@app.delete("/api/v1/files/{file_key}")
async def delete_file(file_key: str):
    """
    Delete an uploaded file from R2 Cloud Storage by its key.
    The key is the UUID filename returned in the upload response (e.g. "abc123.pdf").
    """
    from app.utils.bucket_storage import delete_files

    logger.info(f"Deleting file: {file_key}")
    result = await delete_files(file_key)
    if "error" in result:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=result["error"])
    logger.info(f"File deleted successfully: {file_key}")
    return {"status": "deleted", "file_key": file_key}


@app.get("/")
async def root():
    logger.debug("Health check hit")
    return {"message": "LiveOS Brain is online", "status": "active"}


@app.get("/health")
async def health_check():
    connected = graph_service.verify_connection()
    return {"status": "healthy", "graph": "connected" if connected else "unavailable"}


from app.core.database import get_db  # noqa: E402
from app.models.note import Note  # noqa: E402
from app.schemas.extraction import NoteInput  # noqa: E402
from app.workflows.ingestion import ingestion_workflow  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class ChatInput(BaseModel):
    query: str


from app.schemas.feedback import FeedbackCreate, FeedbackResponse  # noqa: E402
from app.services.feedback import feedback_service  # noqa: E402
from app.workflows.chat import chat_workflow  # noqa: E402


@app.post("/api/v1/chat")
async def chat(input: ChatInput):
    """
    Chat with your Brain: Vector Search -> Rerank -> Synthesis.
    """
    return await chat_workflow.chat(input.query)


@app.post("/api/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    feedback_input: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Persist user feedback for retrieval-quality analysis and future ingestion.
    """
    return await feedback_service.create_feedback(db, feedback_input)


from app.services.graph import graph_service  # noqa: E402


@app.get("/api/v1/graph/summary")
async def get_graph_summary():
    """
    Fetch top themes and nodes for the sidebar.
    """
    rows = graph_service.execute_query("""
        MATCH (n:Node)
        WHERE n.kind IN ['indexable', 'note'] AND n.name IS NOT NULL
        RETURN n.id AS node_id, n.name AS name, n.type AS type
        LIMIT 10
        """)
    return {"themes": rows}


@app.get("/api/v1/graph/visualization")
async def get_graph_visualization():
    """
    Fetch nodes and edges for 2D Force Graph.
    """
    return graph_service.get_full_graph()


@app.get("/api/v1/graph/export")
async def export_graph_for_3d():
    """
    Export full graph data for 3D visualization.
    Returns all Indexable nodes and their relationships in 3d-force-graph format.
    """
    graph_data = graph_service.get_full_graph()
    return graph_data


@app.get("/api/v1/graph/3d/overview")
async def graph_3d_overview():
    """
    Return all community nodes with pre-computed 3D positions.
    Used by the exploration view to render the LOD overview (community spheres only).
    Individual member nodes are fetched lazily via /community/{id}.
    """
    return graph_service.get_3d_overview()


@app.get("/api/v1/graph/3d/community/{community_id}")
async def graph_3d_community(community_id: str):
    """
    Return member nodes and intra-community edges for one community.
    Called by the frontend when the camera flies into a community's radius.
    """
    return graph_service.get_community_members(community_id)


@app.get("/api/v1/graph/3d/full")
async def graph_3d_full():
    """
    Return ALL nodes and ALL edges for the flat spring-layout 3D graph.
    Every Indexable + Community node with pre-computed positions is included.
    Used by the new flat renderer that shows everything at once.
    """
    return graph_service.get_full_3d_graph()


@app.get("/api/v1/graph/3d/node/{node_id}")
async def graph_3d_node_detail(node_id: str):
    """
    Return full detail for a single Indexable node (description, facts, status).
    Called on-demand when the user clicks a card in the 3D graph.
    """
    detail = graph_service.get_node_detail(node_id)
    if detail is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Node not found")
    return detail


# --- Notes API ---


class NoteResponse(BaseModel):
    id: str
    content: str
    created_at: str | None = None
    title: str | None = None
    summary: str | None = None
    processed: bool = False
    failed: bool = False

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
        except Exception:
            # Fallback to dateparser for other formats
            try:
                import dateparser

                dt = dateparser.parse(note_input.created_at)
                if dt:
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    c_at = dt
            except Exception:
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
        except Exception:
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
    failed: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get all notes sorted by creation date (newest first).
    Optionally filter by processed/failed status.
    """
    base_query = select(Note)

    # Apply filters
    filters = []
    if search:
        term = f"%{search}%"
        filters.append((Note.title.ilike(term)) | (Note.content.ilike(term)))

    if processed is not None:
        filters.append(Note.processed == processed)

    if failed is not None:
        filters.append(Note.failed == failed)

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


@app.get("/api/v1/notes/{note_id}/status")
async def get_note_ingestion_status(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the ingestion status of a note without fetching its full content.
    Useful for polling after triggering background ingestion.

    Returns:
      - processed: true once ingestion completes successfully
      - failed: true if the ingestion pipeline encountered a permanent error
      - status: "completed" | "failed" | "processing"
    """
    result = await db.execute(
        select(Note.id, Note.processed, Note.failed).where(Note.id == note_id)
    )
    row = result.one_or_none()

    if row is None:
        return {"error": "Note not found"}, 404

    note_id, processed, failed = row
    if processed:
        status = "completed"
    elif failed:
        status = "failed"
    else:
        status = "processing"

    return {"id": note_id, "processed": processed, "failed": failed, "status": status}


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
        except Exception:
            # Fallback to dateparser for other formats
            try:
                import dateparser

                dt = dateparser.parse(note_input.created_at)
                if dt:
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    existing_note.created_at = dt
            except Exception:
                pass

    existing_note.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(existing_note)

    return existing_note


@app.delete("/api/v1/notes/{note_id}")
async def delete_note(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a note from Postgres and the graph.
    """
    # 1. Delete from Postgres
    await db.execute(delete(Note).where(Note.id == note_id))
    await db.commit()

    # 2. Delete from graph
    graph_service.execute_query(
        "MATCH (n:Node {id: $id}) WHERE n.kind = 'note' DETACH DELETE n",
        {"id": note_id},
    )

    return {"status": "deleted", "id": note_id}


# --- Admin ---


@app.post("/api/v1/admin/rebuild-communities")
async def rebuild_communities(background_tasks: BackgroundTasks):
    """
    Trigger a full Leiden community detection pass in the background.

    Useful when community detection was cancelled or never ran after ingestion.
    The job runs asynchronously; poll the server logs for progress.
    """
    background_tasks.add_task(ingestion_workflow.rebuild_leiden_communities)
    return {
        "status": "started",
        "message": "Leiden community recompute triggered. Check server logs for progress.",
    }
