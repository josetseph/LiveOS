"""FastAPI application entry point: routes, middleware, and startup hooks."""

# pylint: disable=wrong-import-order,wrong-import-position,import-outside-toplevel
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

# Setup logging before any other imports — must precede service imports so
# every module that calls get_logger() at import time finds logging configured.
from app.core.log import get_logger, setup_logging

setup_logging()

from app.core.database import get_db  # noqa: E402
from app.models.note import Note  # noqa: E402
from app.schemas.extraction import NoteInput  # noqa: E402
from app.schemas.note import CreateNoteInput  # noqa: E402
from app.services.graph import graph_service  # noqa: E402
from app.workflows.chat import chat_workflow  # noqa: E402
from app.workflows.ingestion import ingestion_workflow  # noqa: E402
from fastapi import (  # noqa: E402
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

logger = get_logger("API")  # App logger; avoid uvicorn.access formatter expectations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date_str(s: str) -> datetime:
    """Parse a date string, trying ISO format first then dateparser.

    Always returns a timezone-aware datetime. Falls back to utcnow() when
    every parse attempt fails so callers never receive a bare None.
    """
    from dateutil import parser as dateutil_parser

    try:
        dt = dateutil_parser.isoparse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    try:
        import dateparser

        dt = dateparser.parse(s)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    return datetime.now(timezone.utc)


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
    """Initialize external services and database tables on application startup."""
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
        raise HTTPException(status_code=500, detail=result["error"])
    logger.info(f"File deleted successfully: {file_key}")
    return {"status": "deleted", "file_key": file_key}


@app.get("/")
async def root():
    """Root endpoint returning a simple service-status greeting."""
    logger.debug("Health check hit")
    return {"message": "LiveOS Brain is online", "status": "active"}


@app.get("/health")
async def health_check():
    """Health-check endpoint confirming the API is running."""
    connected = graph_service.verify_connection()
    return {"status": "healthy", "graph": "connected" if connected else "unavailable"}


class ChatInput(BaseModel):
    """Request body for the chat endpoint."""

    query: str


@app.post("/api/v1/chat")
async def chat(body: ChatInput):
    """
    Chat with your Brain: Vector Search -> Rerank -> Synthesis.
    """
    return await chat_workflow.chat(body.query)


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
        raise HTTPException(status_code=404, detail="Node not found")
    return detail


# --- Notes API ---


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
    c_at = (
        _parse_date_str(note_input.created_at)
        if note_input.created_at
        else datetime.now(timezone.utc)
    )

    new_note = Note(
        id=note_id,
        content=note_input.content,
        created_at=c_at,
        processed=False,
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

    note_data = NoteInput(
        content=note.content,
        created_at=note.created_at.isoformat() if note.created_at else None,
    )

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
    c_at = (
        _parse_date_str(note_data.created_at)
        if note_data.created_at
        else datetime.now(timezone.utc)
    )

    new_note = Note(
        id=note_id, content=note_data.content, created_at=c_at, processed=False
    )
    db.add(new_note)
    await db.commit()

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
        "processed": False,
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
    try:
        result = await db.execute(
            select(Note.id, Note.processed, Note.failed).where(Note.id == note_id)
        )
        row = result.one_or_none()
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable, retry shortly"
        ) from exc

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

    existing_note.content = note_input.content

    if note_input.created_at:
        existing_note.created_at = _parse_date_str(note_input.created_at)

    existing_note.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(existing_note)

    return existing_note


@app.delete("/api/v1/notes/{note_id}")
async def delete_note(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Delete a note from Postgres and the graph.
    """
    await db.execute(delete(Note).where(Note.id == note_id))
    await db.commit()

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
