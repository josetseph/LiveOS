"""FastAPI application entry point: routes, middleware, and startup hooks."""

# pylint: disable=wrong-import-order,wrong-import-position,import-outside-toplevel
import asyncio
import os
import subprocess
import tempfile
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
from app.services.kb_registry import KBContext, kb_registry  # noqa: E402
from app.workflows.chat import chat_workflow  # noqa: E402
from app.workflows.ingestion import ingestion_workflow  # noqa: E402
from fastapi import (  # noqa: E402
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
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
# KB dependency
# ---------------------------------------------------------------------------


def get_kb(
    kb: str = Query(default="default", description="Knowledge base name or slug")
) -> KBContext:
    """FastAPI dependency: resolve the requested KB from the registry.

    Pass ``?kb=<name>`` in the query string.  Omitting the parameter selects
    the default knowledge base, which is backward-compatible with all existing
    clients.
    """
    ctx = kb_registry.get_kb_by_name(kb)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb}' not found")
    return ctx


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


app = FastAPI(title="LiveOS API", version="0.1.0")

# CORS setup used to allow connections from Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3700", "http://localhost:3701"],
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
    logger.info("Application startup: LiveOS API online")
    # Apply any runtime overrides that were saved from a previous session
    from app.core import runtime_config

    overrides = runtime_config.load()
    if overrides:
        runtime_config.apply_to_settings(overrides)
        logger.info(
            "Runtime config overrides applied",
            extra={"overrides": list(overrides.keys())},
        )


_AUDIO_CONTENT_TYPES = {"audio/webm", "audio/ogg", "audio/opus", "audio/x-matroska"}
_AUDIO_EXTENSIONS = {"webm", "ogg", "opus"}


async def _transcode_to_m4a(content: bytes, src_ext: str) -> tuple[bytes, str]:
    """Transcode audio bytes → AAC/M4A via ffmpeg.

    Returns ``(transcoded_bytes, "m4a")`` on success, or the original
    ``(content, src_ext)`` if ffmpeg is unavailable or fails (graceful fallback).
    """

    def _run() -> tuple[bytes, str]:
        tmp_in = tmp_out = None
        try:
            fd, tmp_in = tempfile.mkstemp(suffix=f".{src_ext}")
            os.write(fd, content)
            os.close(fd)
            tmp_out = tmp_in[: tmp_in.rfind(".")] + ".m4a"
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    tmp_in,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    tmp_out,
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                with open(tmp_out, "rb") as f:
                    return f.read(), "m4a"
            logger.warning(
                "FFmpeg transcoding failed",
                extra={"stderr": result.stderr.decode(errors="replace")[:500]},
            )
        except FileNotFoundError:
            logger.warning(
                "ffmpeg not found on PATH — storing audio without transcoding"
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "ffmpeg transcoding timed out — storing audio without transcoding"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audio transcoding error", extra={"error": str(exc)})
        finally:
            if tmp_in and os.path.exists(tmp_in):
                os.unlink(tmp_in)
            if tmp_out and os.path.exists(tmp_out):
                os.unlink(tmp_out)
        return content, src_ext

    return await asyncio.to_thread(_run)


@app.post("/api/v1/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file to R2 Cloud Storage.
    Audio files (WebM, OGG, Opus) are transcoded to AAC/M4A so they play in
    all browsers including Safari, which does not support WebM.
    """
    from app.utils.bucket_storage import get_files, send_files

    logger.info(f"Uploading file: {file.filename}")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    content_type = file.content_type or ""
    content = await file.read()

    # Transcode audio to M4A for universal playback compatibility
    if content_type in _AUDIO_CONTENT_TYPES or ext in _AUDIO_EXTENSIONS:
        content, ext = await _transcode_to_m4a(content, ext)
        content_type = "audio/mp4"

    filename = f"{uuid.uuid4()}.{ext}"

    # Upload to storage
    await send_files(content, filename, content_type)

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
    return {"message": "LiveOS is online", "status": "active"}


@app.get("/health")
async def health_check(kb: KBContext = Depends(get_kb)):
    """Health-check endpoint confirming the API is running."""
    connected = kb.graph.verify_connection()
    return {"status": "healthy", "graph": "connected" if connected else "unavailable"}


class ChatInput(BaseModel):
    """Request body for the chat endpoint."""

    query: str


class LLMSettings(BaseModel):
    """Request body for updating runtime LLM settings."""

    provider: str | None = None
    model: str | None = None
    ingestion_model: str | None = None
    base_url: str | None = None


@app.get("/api/v1/settings")
async def get_runtime_settings():
    """Return the current effective chat and ingestion LLM settings."""
    from app.core import runtime_config
    from app.core.config import settings
    from app.services.llm import llm_service

    return {
        "provider": settings.LLM_PROVIDER,
        "model": llm_service._get_model_for_task("chat") or settings.LLM_MODEL,
        "ingestion_model": llm_service._get_ingestion_model() or settings.LLM_MODEL,
        "base_url": settings.LLM_BASE_URL,
    }


@app.patch("/api/v1/settings")
async def update_runtime_settings(body: LLMSettings):
    """Update the active LLM provider, model, or base URL without restarting the server.

    Model-only changes take effect immediately (no client reinitialization needed).
    Provider or base URL changes trigger a full LLM client reinitalization.
    API keys are never accepted here — configure those in .env.
    """
    from app.core import runtime_config
    from app.core.config import settings
    from app.services.llm import llm_service

    overrides = runtime_config.load()

    provider_changed = bool(body.provider and body.provider != settings.LLM_PROVIDER)
    base_url_changed = bool(body.base_url and body.base_url != settings.LLM_BASE_URL)

    if body.provider is not None:
        overrides["provider"] = body.provider
        settings.LLM_PROVIDER = body.provider
    if body.model is not None:
        overrides["model"] = body.model
        settings.CHAT_MODEL = body.model
    if body.ingestion_model is not None:
        overrides["ingestion_model"] = body.ingestion_model
        settings.INGESTION_MODEL = body.ingestion_model
    if body.base_url is not None:
        overrides["base_url"] = body.base_url
        settings.LLM_BASE_URL = body.base_url

    runtime_config.save(overrides)

    if provider_changed or base_url_changed:
        llm_service.provider = settings.LLM_PROVIDER.lower()
        llm_service._init_clients()
        logger.info(
            "LLM clients reinitialized",
            extra={"provider": llm_service.provider, "base_url": settings.LLM_BASE_URL},
        )

    return {
        "provider": settings.LLM_PROVIDER,
        "model": settings.CHAT_MODEL or settings.LLM_MODEL,
        "ingestion_model": settings.INGESTION_MODEL or settings.LLM_MODEL,
        "base_url": settings.LLM_BASE_URL,
    }


@app.post("/api/v1/chat")
async def chat(body: ChatInput, kb: KBContext = Depends(get_kb)):
    """
    Chat with your Brain: Vector Search -> Rerank -> Synthesis.
    """
    return await kb.get_chat_workflow().chat(body.query)


@app.get("/api/v1/graph/summary")
async def get_graph_summary(kb: KBContext = Depends(get_kb)):
    """
    Fetch top themes and nodes for the sidebar.
    """
    rows = kb.graph.execute_query("""
        MATCH (n:Node)
        WHERE n.kind IN ['indexable', 'note'] AND n.name IS NOT NULL
        RETURN n.id AS node_id, n.name AS name, n.type AS type
        LIMIT 10
        """)
    return {"themes": rows}


@app.get("/api/v1/graph/visualization")
async def get_graph_visualization(kb: KBContext = Depends(get_kb)):
    """
    Fetch nodes and edges for 2D Force Graph.
    """
    return kb.graph.get_full_graph()


@app.get("/api/v1/graph/3d/overview")
async def graph_3d_overview(kb: KBContext = Depends(get_kb)):
    """
    Return all community nodes with pre-computed 3D positions.
    Used by the exploration view to render the LOD overview (community spheres only).
    Individual member nodes are fetched lazily via /community/{id}.
    """
    return kb.graph.get_3d_overview()


@app.get("/api/v1/graph/3d/community/{community_id}")
async def graph_3d_community(community_id: str, kb: KBContext = Depends(get_kb)):
    """
    Return member nodes and intra-community edges for one community.
    Called by the frontend when the camera flies into a community's radius.
    """
    return kb.graph.get_community_members(community_id)


@app.get("/api/v1/graph/3d/full")
async def graph_3d_full(kb: KBContext = Depends(get_kb)):
    """
    Return ALL nodes and ALL edges for the flat spring-layout 3D graph.
    Every Indexable + Community node with pre-computed positions is included.
    Used by the new flat renderer that shows everything at once.
    """
    return kb.graph.get_full_3d_graph()


@app.get("/api/v1/graph/3d/node/{node_id}")
async def graph_3d_node_detail(node_id: str, kb: KBContext = Depends(get_kb)):
    """
    Return full detail for a single Indexable node (description, facts, status).
    Called on-demand when the user clicks a card in the 3D graph.
    """
    detail = kb.graph.get_node_detail(node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return detail


# --- Notes API ---


@app.post("/api/v1/notes")
async def create_note(
    note_input: CreateNoteInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
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
        kb_id=kb.kb_id,
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
    kb: KBContext = Depends(get_kb),
):
    """
    Trigger (or re-trigger) ingestion for an existing note.
    Always force-reingests — resets processed=False so the pipeline runs regardless
    of prior ingestion status.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()

    if not note:
        return {"error": "Note not found"}, 404

    # Reset processed flag so the pipeline treats this as a fresh ingestion.
    note.processed = False
    await db.commit()

    note_data = NoteInput(
        content=note.content,
        created_at=note.created_at.isoformat() if note.created_at else None,
    )

    background_tasks.add_task(
        kb.get_ingestion_workflow().process_note, note_data, note_id
    )

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
    kb: KBContext = Depends(get_kb),
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
        background_tasks.add_task(
            kb.get_ingestion_workflow().process_note, note_data, note_id
        )
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
    kb: KBContext = Depends(get_kb),
):
    """
    Get notes for the active KB, sorted by creation date (newest first).
    Optionally filter by processed/failed status.
    """
    base_query = select(Note)

    filters = [Note.kb_id == kb.kb_id]
    if search:
        term = f"%{search}%"
        filters.append((Note.title.ilike(term)) | (Note.content.ilike(term)))

    if processed is not None:
        filters.append(Note.processed == processed)

    if failed is not None:
        filters.append(Note.failed == failed)

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
async def delete_note(
    note_id: str, db: AsyncSession = Depends(get_db), kb: KBContext = Depends(get_kb)
):
    """
    Delete a note from Postgres, the graph, Qdrant, and Typesense.

    Entity nodes that are referenced ONLY by this note are orphaned after the note
    is removed, so they are deleted from all stores. Shared entities (referenced by
    other notes) are left intact.
    """
    # 1. Find entity node IDs linked exclusively to this note in the graph.
    rows = kb.graph.execute_query(
        """
        MATCH (note:Node {id: $note_id, kind: 'note'})-[:REFERENCES]->(entity:Node)
        WHERE entity.kind <> 'note'
          AND NOT EXISTS {
            MATCH (other:Node {kind: 'note'})-[:REFERENCES]->(entity)
            WHERE other.id <> $note_id
          }
        RETURN entity.id AS entity_id
        """,
        {"note_id": note_id},
    )
    orphan_ids: list[str] = [r["entity_id"] for r in (rows or []) if r.get("entity_id")]

    # 2. Delete the note row from Postgres.
    await db.execute(delete(Note).where(Note.id == note_id))
    await db.commit()

    # 3. Remove the note node (and all its edges) from the graph.
    kb.graph.execute_query(
        "MATCH (n:Node {id: $id}) WHERE n.kind = 'note' DETACH DELETE n",
        {"id": note_id},
    )

    # 4. Delete orphaned entity nodes from graph, Qdrant, and Typesense.
    for entity_id in orphan_ids:
        kb.graph.execute_query(
            "MATCH (n:Node {id: $id}) DETACH DELETE n",
            {"id": entity_id},
        )
        try:
            kb.qdrant.delete_node(entity_id)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        try:
            kb.typesense.delete_node(entity_id)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    logger.info(
        f"[delete_note] Deleted note {note_id}; removed {len(orphan_ids)} orphaned entity nodes."
    )
    return {"status": "deleted", "id": note_id, "orphans_removed": len(orphan_ids)}


# --- Admin ---


@app.post("/api/v1/admin/rebuild-communities")
async def rebuild_communities(
    background_tasks: BackgroundTasks, kb: KBContext = Depends(get_kb)
):
    """
    Trigger a full Leiden community detection pass in the background.

    Useful when community detection was cancelled or never ran after ingestion.
    The job runs asynchronously; poll the server logs for progress.
    """
    background_tasks.add_task(kb.get_ingestion_workflow().rebuild_leiden_communities)
    return {
        "status": "started",
        "message": "Leiden community recompute triggered. Check server logs for progress.",
    }


# ---------------------------------------------------------------------------
# Knowledge-base management
# ---------------------------------------------------------------------------


class CreateKBInput(BaseModel):
    """Request body for creating a new knowledge base."""

    name: str


class RenameKBInput(BaseModel):
    """Request body for renaming a knowledge base."""

    name: str


@app.get("/api/v1/kb")
async def list_knowledge_bases():
    """List all registered knowledge bases."""
    return {"knowledge_bases": kb_registry.list_kbs()}


@app.post("/api/v1/kb", status_code=201)
async def create_knowledge_base(body: CreateKBInput):
    """Create a new knowledge base.

    Provision separate Kuzu, Qdrant, and Typesense stores for the new KB.
    The KB is immediately available for ingestion and retrieval via ``?kb=<name>``.
    """
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400, detail="Knowledge base name must not be empty"
        )
    ctx = kb_registry.create_kb(body.name.strip())
    return {
        "id": ctx.kb_id,
        "name": ctx.name,
        "message": f"Knowledge base '{ctx.name}' created. Use ?kb={ctx.name} to target it.",
    }


@app.delete("/api/v1/kb/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: str):
    """Delete a knowledge base and all its associated data.

    This permanently drops the Kuzu directory, Qdrant collections, and Typesense
    collection for the specified KB. The default KB cannot be deleted.
    """
    if kb_id == "default":
        raise HTTPException(
            status_code=400, detail="The default knowledge base cannot be deleted"
        )
    deleted = kb_registry.delete_kb(kb_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Knowledge base '{kb_id}' not found"
        )


@app.patch("/api/v1/kb/{kb_id}")
async def rename_knowledge_base(kb_id: str, body: RenameKBInput):
    """Rename a knowledge base. The slug and UUID are unchanged; only the display name is updated."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name must not be empty")
    try:
        success = kb_registry.rename_kb(kb_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Knowledge base '{kb_id}' not found"
        )
    return {"id": kb_id, "name": name}
