"""FastAPI application entry point: routes, middleware, and startup hooks."""

# pylint: disable=wrong-import-order,wrong-import-position,import-outside-toplevel
import asyncio
import os
import subprocess
import tempfile
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

# Setup logging before any other imports — must precede service imports so
# every module that calls get_logger() at import time finds logging configured.
from app.core.log import get_logger, setup_logging

setup_logging()

from app.core.config import settings  # noqa: E402
from app.core.database import get_db, init_db  # noqa: E402
from app.models.note import Note  # noqa: E402
from app.schemas.chat import CreateConversationInput
from app.services.chat_store import chat_store
from app.schemas.extraction import NoteInput  # noqa: E402
from app.schemas.note import (  # noqa: E402
    CreateNoteInput,
    DeleteVaultFileInput,
    MoveNoteInput,
    MoveVaultFileInput,
)
from app.services.kb_registry import KBContext, kb_registry  # noqa: E402
from app.api_desktop import router as desktop_router  # noqa: E402
from app.services.firefly_service import firefly_service  # noqa: E402
from app.services.note_files import note_body, persist_note_body  # noqa: E402
from app.services.wikilinks import refresh_note_links  # noqa: E402
from app.services.vault import delete_note_file, clear_vault_contents, ensure_vault  # noqa: E402
from app.services.ai_gate import require_ai, ai_is_configured  # noqa: E402
from app.models.wikilink import NoteLink  # noqa: E402
from pathlib import Path  # noqa: E402
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
from sqlalchemy import delete, or_, select, update  # noqa: E402
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
app.include_router(desktop_router)

cors_origins = [
    origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()
]

# CORS setup used to allow connections from Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
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
    await init_db()
    from app.core import runtime_config

    overrides = runtime_config.load()
    if overrides:
        runtime_config.apply_to_settings(overrides)
        logger.info(
            "Runtime config overrides applied",
            extra={"overrides": list(overrides.keys())},
        )
    # Align Qdrant collection dims with the selected embed model before any ingest.
    try:
        from app.services.local_models import sync_embedding_infrastructure

        sync_embedding_infrastructure()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(f"Embedding infrastructure sync skipped: {exc}")
    try:
        from app.services.vault_watcher import start_vault_watchers

        start_vault_watchers()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(f"Vault watcher not started: {exc}")


@app.on_event("shutdown")
async def shutdown_event():
    try:
        from app.services.vault_watcher import stop_vault_watchers

        stop_vault_watchers()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def _note_response(note: Note, kb: KBContext) -> dict:
    """Serialize note with vault-backed content."""
    return {
        "id": note.id,
        "content": note_body(note, kb),
        "title": note.title,
        "rel_path": note.rel_path,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "processed": note.processed,
        "failed": note.failed,
        "processing_stage": note.processing_stage,
        "processing_model": note.processing_model,
        "kb_id": note.kb_id,
    }


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
                check=False,
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
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Audio transcoding error", extra={"error": str(exc)})
        finally:
            if tmp_in and os.path.exists(tmp_in):
                os.unlink(tmp_in)
            if tmp_out and os.path.exists(tmp_out):
                os.unlink(tmp_out)
        return content, src_ext

    return await asyncio.to_thread(_run)


@app.post("/api/v1/upload")
async def upload_file(
    file: UploadFile = File(...),
    kb: KBContext = Depends(get_kb),
):
    """Upload a file into the current KB vault attachments folder."""
    logger.info(f"Uploading file: {file.filename}")

    if not kb.vault_path:
        raise HTTPException(status_code=400, detail="No vault configured for this knowledge base")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    content_type = file.content_type or ""
    content = await file.read()

    if content_type in _AUDIO_CONTENT_TYPES or ext in _AUDIO_EXTENSIONS:
        content, ext = await _transcode_to_m4a(content, ext)
        content_type = "audio/mp4"
        filename_hint = f"recording.{ext}"
    else:
        filename_hint = file.filename or f"file.{ext}"

    # Always store in the KB vault (no S3 for LifeOS desktop/local).
    from app.services.local_storage import store_upload

    try:
        result = await store_upload(Path(kb.vault_path), filename_hint, content, kb.kb_id)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Vault upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    logger.info(f"File uploaded to vault: {result['url']}")
    # Prefer vault-relative path in markdown for portability; also return href for UI.
    return {
        "filename": file.filename,
        "url": result["url"],
        "href": result["url"],
        "rel_path": result["key"],
        "local_path": result["url"],
        "key": result["key"],
        "status": "success",
    }


@app.delete("/api/v1/files/{file_key}")
async def delete_file(file_key: str, kb: KBContext = Depends(get_kb)):
    """Delete an uploaded vault attachment (or legacy S3 object)."""
    logger.info(f"Deleting file: {file_key}")
    if settings.STORAGE_BACKEND == "s3":
        from app.utils.bucket_storage import delete_files

        result = await delete_files(file_key)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
    else:
        from app.services.local_storage import remove_upload

        await remove_upload(Path(kb.vault_path), file_key)
    logger.info(f"File deleted successfully: {file_key}")
    return {"status": "deleted", "file_key": file_key}


@app.get("/")
async def root():
    """Root endpoint returning a simple service-status greeting."""
    logger.debug("Health check hit")
    return {"message": "LiveOS is online", "status": "active"}


@app.get("/health")
async def health_check():
    """Lightweight liveness probe for the desktop supervisor (no KB/graph deps)."""
    return {"status": "healthy"}


class ChatInput(BaseModel):
    """Request body for the chat endpoint."""

    query: str
    request_id: str | None = None
    conversation_id: str | None = None


_chat_status: dict[str, dict] = {}
_chat_job_lock = threading.Lock()


class LLMSettings(BaseModel):
    """Request body for updating runtime LLM settings."""

    provider: str | None = None
    model: str | None = None
    ingestion_model: str | None = None
    base_url: str | None = None


class ScanTextInput(BaseModel):
    """Request body for scanning a text block for entity mentions."""

    text: str


@app.get("/api/v1/settings")
async def get_runtime_settings():
    """Return the current effective chat and ingestion LLM settings."""
    from app.core.config import settings
    from app.services.llm import llm_service

    return {
        "provider": settings.LLM_PROVIDER,
        "model": llm_service.get_chat_model() or settings.LLM_MODEL,
        "ingestion_model": llm_service.get_ingestion_model() or settings.LLM_MODEL,
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
        llm_service.init_clients()
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


@app.get("/api/v1/chat/conversations")
async def list_chat_conversations(kb: KBContext = Depends(get_kb)):
    """List saved chat conversations for the active knowledge base."""
    return await chat_store.list_conversations(kb.kb_id)


@app.post("/api/v1/chat/conversations")
async def create_chat_conversation(
    body: CreateConversationInput | None = None,
    kb: KBContext = Depends(get_kb),
):
    """Create an empty chat conversation."""
    title = body.title if body else None
    return await chat_store.create_conversation(kb.kb_id, title=title)


@app.get("/api/v1/chat/conversations/{conversation_id}/messages")
async def get_chat_messages(conversation_id: str):
    """Return all messages for a conversation."""
    conv = await chat_store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await chat_store.list_messages(conversation_id)


@app.delete("/api/v1/chat/conversations/{conversation_id}")
async def delete_chat_conversation(conversation_id: str):
    """Soft-delete a chat conversation."""
    deleted = await chat_store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}


@app.post("/api/v1/chat")
async def chat(body: ChatInput, kb: KBContext = Depends(get_kb)):
    """
    Chat with your Brain: Vector Search -> Rerank -> Synthesis.
    """
    require_ai()
    from app.schemas.chat import ChatTurn

    request_id = body.request_id or str(uuid.uuid4())
    conversation = await chat_store.ensure_conversation(
        body.conversation_id, kb.kb_id
    )
    conversation_id = conversation["id"]
    history = await chat_store.get_recent_history(conversation_id)
    history_turns = history

    def _progress(stage: str, model: str | None = None) -> None:
        _chat_status[request_id] = {"stage": stage, "model": model}

    _progress("Starting chat request")
    try:
        await chat_store.add_message(conversation_id, "user", body.query)
        await chat_store.maybe_set_title_from_first_message(conversation_id, body.query)
        if firefly_service.looks_like_finance_query(body.query):
            _progress("Checking finance data and notes")
            note_ctx = await kb.get_chat_workflow().retrieve_for_query(
                body.query,
                history=history_turns,
                progress_callback=_progress,
            )
            result = await firefly_service.answer_finance_question(
                body.query,
                kb,
                note_docs=note_ctx.get("context") or [],
                rewritten_query=note_ctx.get("rewritten_query"),
            )
            if note_ctx.get("thinking"):
                result["thinking"] = note_ctx.get("thinking")
        else:
            result = await kb.get_chat_workflow().chat(
                body.query,
                history=history_turns,
                progress_callback=_progress,
            )
        assistant = await chat_store.add_message(
            conversation_id,
            "assistant",
            result.get("answer", ""),
            thinking=result.get("thinking"),
            metadata={
                "rewritten_query": result.get("rewritten_query"),
                "context_count": len(result.get("context") or []),
            },
        )
        _progress("Complete")
        result["request_id"] = request_id
        result["conversation_id"] = conversation_id
        result["assistant_message_id"] = assistant["id"]
        return result
    except Exception:
        _progress("Failed")
        raise


async def _run_chat_job(
    request_id: str,
    query: str,
    kb: KBContext,
    conversation_id: str,
    history: list[dict],
) -> None:
    """Run a long chat request after the browser has received a request id."""
    from app.schemas.chat import ChatTurn

    history_turns = [ChatTurn(**t) for t in history]

    def _progress(stage: str, model: str | None = None) -> None:
        current = _chat_status.get(request_id, {})
        _chat_status[request_id] = {
            **current,
            "stage": stage,
            "model": model,
            "done": False,
            "conversation_id": conversation_id,
        }

    _progress("Starting chat request")
    try:
        if firefly_service.looks_like_finance_query(query):
            _progress("Checking finance data and notes")
            note_ctx = await kb.get_chat_workflow().retrieve_for_query(
                query,
                history=history_turns,
                progress_callback=_progress,
            )
            result = await firefly_service.answer_finance_question(
                query,
                kb,
                note_docs=note_ctx.get("context") or [],
                rewritten_query=note_ctx.get("rewritten_query"),
            )
            if note_ctx.get("thinking"):
                result["thinking"] = note_ctx.get("thinking")
        else:
            result = await kb.get_chat_workflow().chat(
                query,
                history=history_turns,
                progress_callback=_progress,
            )
        assistant = await chat_store.add_message(
            conversation_id,
            "assistant",
            result.get("answer", ""),
            thinking=result.get("thinking"),
            metadata={
                "rewritten_query": result.get("rewritten_query"),
                "context_count": len(result.get("context") or []),
            },
        )
        result["request_id"] = request_id
        result["conversation_id"] = conversation_id
        result["assistant_message_id"] = assistant["id"]
        _chat_status[request_id] = {
            "stage": "Complete",
            "model": None,
            "done": True,
            "conversation_id": conversation_id,
            "result": result,
        }
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("[Chat] Async chat job failed")
        _chat_status[request_id] = {
            "stage": "Failed",
            "model": None,
            "done": True,
            "conversation_id": conversation_id,
            "error": str(exc) or exc.__class__.__name__,
        }


def _run_chat_job_sync(
    request_id: str,
    query: str,
    kb: KBContext,
    conversation_id: str,
    history: list[dict],
) -> None:
    """Threadpool entry point for long chat jobs."""
    if not _chat_job_lock.acquire(blocking=False):
        current = _chat_status.get(request_id, {})
        _chat_status[request_id] = {
            **current,
            "stage": "Waiting for current chat to finish",
            "model": None,
            "done": False,
            "conversation_id": conversation_id,
        }
        _chat_job_lock.acquire()
    try:
        asyncio.run(
            _run_chat_job(request_id, query, kb, conversation_id, history)
        )
    finally:
        _chat_job_lock.release()


@app.post("/api/v1/chat/async")
async def start_chat(
    body: ChatInput,
    background_tasks: BackgroundTasks,
    kb: KBContext = Depends(get_kb),
):
    """Start a chat request and return immediately for polling clients."""
    require_ai()
    request_id = body.request_id or str(uuid.uuid4())
    conversation = await chat_store.ensure_conversation(
        body.conversation_id, kb.kb_id
    )
    conversation_id = conversation["id"]
    history = await chat_store.get_recent_history(conversation_id)
    history_payload = [{"role": t.role, "content": t.content} for t in history]

    await chat_store.add_message(conversation_id, "user", body.query)
    await chat_store.maybe_set_title_from_first_message(conversation_id, body.query)

    _chat_status[request_id] = {
        "stage": "Queued",
        "model": None,
        "done": False,
        "conversation_id": conversation_id,
    }
    background_tasks.add_task(
        _run_chat_job_sync,
        request_id,
        body.query,
        kb,
        conversation_id,
        history_payload,
    )
    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "stage": "Queued",
        "model": None,
        "done": False,
    }


@app.get("/api/v1/chat/status/{request_id}")
async def get_chat_status(request_id: str):
    """Return current progress for a non-streaming chat request."""
    return {
        "request_id": request_id,
        **_chat_status.get(
            request_id, {"stage": "Waiting", "model": None, "done": False}
        ),
    }


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

    # Meili fallback when Qdrant has structural presence but empty content payloads.
    needs_content = not (detail.get("description") or detail.get("isolated_contexts"))
    if needs_content:
        try:
            doc = kb.typesense.get_node(node_id)
        except Exception:  # pylint: disable=broad-exception-caught
            doc = None
        if doc is not None and not isinstance(doc, dict):
            # Defensive: older Meili clients return Document objects.
            try:
                doc = dict(doc)  # type: ignore[arg-type]
            except Exception:  # pylint: disable=broad-exception-caught
                doc = {
                    k: getattr(doc, k)
                    for k in (
                        "node_id",
                        "name",
                        "type",
                        "isolated_contexts",
                        "relationship_natural_language",
                        "community_level",
                    )
                    if getattr(doc, k, None) is not None
                }
        if isinstance(doc, dict):
            if not detail.get("name") and doc.get("name"):
                detail["name"] = doc["name"]
            if not detail.get("node_type") and doc.get("type"):
                detail["node_type"] = doc["type"]
            ctx = doc.get("isolated_contexts") or ""
            if isinstance(ctx, str) and ctx.strip():
                # Meili stores contexts as a joined string.
                parts = [p.strip() for p in ctx.split(" | ") if p.strip()]
                if not parts:
                    parts = [ctx.strip()]
                detail["isolated_contexts"] = parts
                if not detail.get("description"):
                    detail["description"] = parts[0]
                    detail["summary"] = parts[0]
            elif isinstance(ctx, list) and ctx:
                detail["isolated_contexts"] = [str(x) for x in ctx if x]
                if not detail.get("description"):
                    detail["description"] = str(ctx[0])
                    detail["summary"] = str(ctx[0])

    # Prefer DB/Qdrant titles over empty/placeholder graph node.name values
    # (legacy rows can show as "Unknown" on REFERENCES connections).
    related = detail.get("related_notes") or []
    connections = detail.get("connections") or []

    def _needs_title(name: object) -> bool:
        n = (str(name) if name is not None else "").strip()
        return not n or n.lower() in {"unknown", "untitled", "untitled note"}

    resolve_ids: set[str] = set()
    for n in related:
        nid = n.get("note_id")
        if nid and _needs_title(n.get("name")):
            resolve_ids.add(str(nid))
    for c in connections:
        cid = c.get("node_id")
        if cid and _needs_title(c.get("name")):
            resolve_ids.add(str(cid))

    resolved: dict[str, str] = {}
    if resolve_ids:
        try:
            from pathlib import Path

            from sqlalchemy import select

            from app.core.database import AsyncSessionLocal
            from app.models.note import Note

            async with AsyncSessionLocal() as session:
                rows = (
                    await session.execute(
                        select(Note.id, Note.title, Note.rel_path).where(
                            Note.id.in_(list(resolve_ids))
                        )
                    )
                ).all()
            for rid, title, rel_path in rows:
                if not rid:
                    continue
                label = (title or "").strip()
                if not label and rel_path:
                    label = Path(str(rel_path)).stem.strip()
                if label:
                    resolved[str(rid)] = label
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        still = [i for i in resolve_ids if i not in resolved]
        if still:
            try:
                content_map = kb.qdrant.get_nodes_content_by_ids(still) or {}
                for sid in still:
                    label = (content_map.get(sid) or {}).get("name") or ""
                    if isinstance(label, str) and label.strip():
                        resolved[sid] = label.strip()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    for note in related:
        nid = note.get("note_id")
        if nid and resolved.get(str(nid)):
            note["name"] = resolved[str(nid)]
        elif _needs_title(note.get("name")):
            note["name"] = "Untitled note"

    for conn in connections:
        cid = conn.get("node_id")
        if cid and resolved.get(str(cid)):
            conn["name"] = resolved[str(cid)]
        elif _needs_title(conn.get("name")):
            conn["name"] = (
                "Untitled note" if conn.get("kind") == "note" else "Untitled"
            )

    # Backfill Kuzu so the next hop query returns real names.
    if resolved:
        try:
            for nid, name in resolved.items():
                kb.graph.execute_query(
                    "MATCH (n:Node {id: $id}) SET n.name = $name",
                    {"id": nid, "name": name},
                )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    return detail


@app.get("/api/v1/graph/entities/search")
async def search_entities_autocomplete(
    q: str,
    limit: int = 5,
    kb: KBContext = Depends(get_kb),
):
    """
    Search entity nodes by name for autocomplete suggestions in the notes editor.
    Returns only indexable entities (excludes notes and community nodes).
    """
    import re as _re

    if not q or len(q.strip()) < 2:
        return []
    if not ai_is_configured():
        return []

    hits = kb.typesense.search_nodes(q.strip(), limit * 2)
    results: list[dict] = []
    for hit in hits:
        payload = hit.get("payload", {})
        node_type = payload.get("type", "")
        node_id = payload.get("node_id", "")
        name = payload.get("name", "")
        if not node_id or not name:
            continue
        if node_type in ("note", "community"):
            continue
        results.append({"node_id": node_id, "name": name, "node_type": node_type})
        if len(results) >= limit:
            break
    return results


@app.post("/api/v1/graph/entities/scan-text")
async def scan_entities_in_text(
    body: ScanTextInput,
    kb: KBContext = Depends(get_kb),
):
    """
    Scan a text block for entity mentions and return found entities.
    Used to auto-highlight entity names in existing notes on load.
    """
    import re as _re

    text = body.text
    if not text or len(text.strip()) < 3:
        return []

    candidates: set[str] = set()

    # Multi-word proper noun sequences: "Clara Sydney", "Project Horizon"
    multi_cap = _re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
    candidates.update(multi_cap)

    # Single capitalised words of 4+ chars (potential proper nouns)
    single_cap = _re.findall(r"\b([A-Z][a-z]{3,})\b", text)
    candidates.update(single_cap)

    if not candidates:
        return []

    found: dict[str, dict] = {}
    for candidate in list(candidates)[:40]:
        hits = kb.typesense.search_nodes(candidate, 2)
        for hit in hits:
            payload = hit.get("payload", {})
            name = payload.get("name", "")
            node_type = payload.get("type", "")
            node_id = payload.get("node_id", "")
            if not node_id or node_type in ("note", "community"):
                continue
            # Only include if the entity name appears verbatim in the text
            if (
                _re.search(_re.escape(name), text, _re.IGNORECASE)
                and node_id not in found
            ):
                found[node_id] = {
                    "node_id": node_id,
                    "name": name,
                    "node_type": node_type,
                }

    return list(found.values())


@app.post("/api/v1/graph/entities/note-subgraph")
async def note_entity_subgraph(
    body: ScanTextInput,
    kb: KBContext = Depends(get_kb),
):
    """
    Entities mentioned in note text + knowledge-graph edges between them.
    Used by the Connected panel "Nodes" mode.
    """
    entities = await scan_entities_in_text(body, kb)
    nodes = [
        {
            "id": e["node_id"],
            "title": e["name"],
            "type": e.get("node_type") or "entity",
        }
        for e in entities
    ]
    id_set = {n["id"] for n in nodes}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    if ai_is_configured() and id_set:
        graph = kb.graph
        for ent in entities:
            try:
                related = graph.get_related_nodes(ent["name"], max_depth=1)
            except Exception:  # pylint: disable=broad-exception-caught
                related = []
            for rel in related:
                tid = rel.get("node_id")
                if not tid or tid not in id_set or tid == ent["node_id"]:
                    continue
                a, b = sorted((ent["node_id"], tid))
                if (a, b) in seen_edges:
                    continue
                seen_edges.add((a, b))
                edges.append(
                    {
                        "source": ent["node_id"],
                        "target": tid,
                        "type": (rel.get("relationship_path") or ["related"])[0]
                        if isinstance(rel.get("relationship_path"), list)
                        else "related",
                    }
                )

    return {"nodes": nodes, "edges": edges, "center_id": None}


# --- Notes API ---


@app.post("/api/v1/notes")
async def create_note(
    note_input: CreateNoteInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Create a note as a vault .md file + metadata row (no ingest)."""
    note_id = str(uuid.uuid4())
    c_at = (
        _parse_date_str(note_input.created_at)
        if note_input.created_at
        else datetime.now(timezone.utc)
    )

    new_note = Note(
        id=note_id,
        content="",
        created_at=c_at,
        processed=False,
        processing_stage="Saved",
        title=(note_input.title or "").strip() or None,
        kb_id=kb.kb_id,
    )
    persist_note_body(
        new_note,
        kb,
        note_input.content or "",
        title=(note_input.title or "").strip() or None,
        folder=(note_input.folder or "").strip() or None,
    )
    db.add(new_note)
    await db.flush()
    await refresh_note_links(db, kb.kb_id, note_id, note_input.content or "")
    await db.commit()
    await db.refresh(new_note)

    return _note_response(new_note, kb)


@app.post("/api/v1/notes/{note_id}/move")
async def move_note(
    note_id: str,
    body: MoveNoteInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Move a note into a vault folder (empty folder = vault root)."""
    from app.services.vault_ops import move_note_to_folder

    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note or note.kb_id != kb.kb_id:
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        moved = await move_note_to_folder(db, kb, note, body.folder or "")
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.refresh(note)
    return {**moved, "note": _note_response(note, kb)}


@app.post("/api/v1/vault/move")
async def move_vault_path(
    body: MoveVaultFileInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Move any vault file (note or attachment) and rewrite markdown links."""
    from app.services.vault_ops import move_vault_file

    try:
        return await move_vault_file(db, kb, body.from_rel, body.to_rel)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/vault/delete")
async def delete_vault_path(
    body: DeleteVaultFileInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Delete a vault attachment and strip markdown links that pointed at it."""
    from app.services.vault_ops import delete_vault_file

    try:
        return await delete_vault_file(db, kb, body.rel_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class MkdirInput(BaseModel):
    path: str = ""


@app.post("/api/v1/vault/mkdir")
async def mkdir_vault_folder(
    body: MkdirInput,
    kb: KBContext = Depends(get_kb),
):
    """Create an empty folder in the vault (for the notes sidebar tree)."""
    if not kb.vault_path:
        raise HTTPException(status_code=400, detail="No vault configured")
    rel = (body.path or "").replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="Invalid folder path")
    try:
        vault = Path(kb.vault_path).expanduser().resolve()
        target = (vault / rel).resolve()
        target.relative_to(vault)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes vault") from exc
    try:
        target.mkdir(parents=True, exist_ok=True)
        keep = target / ".keep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not create folder: {exc}") from exc
    return {"path": rel, "status": "ok"}


@app.get("/api/v1/vault/folders")
async def list_folders(kb: KBContext = Depends(get_kb)):
    from app.services.vault_sync import (
        list_attachment_files,
        list_vault_folders,
        list_vault_media_files,
    )

    if not kb.vault_path:
        return {
            "folders": [],
            "attachments": [],
            "media_files": [],
            "vault_name": "",
            "vault_path": "",
        }
    vault = Path(kb.vault_path).expanduser().resolve()
    # Ensure attachments exists so it appears in the vault tree
    (vault / "attachments").mkdir(parents=True, exist_ok=True)
    media = list_vault_media_files(vault)
    return {
        "folders": list_vault_folders(vault, include_attachments=True),
        "attachments": list_attachment_files(vault),
        "media_files": media,
        "vault_name": vault.name,
        "vault_path": str(vault),
    }


@app.get("/api/v1/vault/local-path")
async def vault_local_path(
    rel: str = Query(..., description="Vault-relative path or /vault-files/... URL"),
    kb: KBContext = Depends(get_kb),
):
    """Resolve a vault-relative path (or vault-files URL) to an absolute local path."""
    if not kb.vault_path:
        raise HTTPException(status_code=400, detail="No vault configured")
    raw = (rel or "").strip().replace("\\", "/")
    # Accept /vault-files/<kb>/attachments/x.png or attachments/x.png
    marker = f"/vault-files/{kb.kb_id}/"
    if raw.startswith("/vault-files/"):
        parts = raw.split("/", 3)  # '', 'vault-files', kb, rest
        raw = parts[3] if len(parts) > 3 else ""
    elif marker in raw:
        raw = raw.split(marker, 1)[1]
    elif raw.startswith("vault-files/"):
        parts = raw.split("/", 2)
        raw = parts[2] if len(parts) > 2 else ""
    raw = raw.lstrip("/")
    if not raw or ".." in raw.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    vault = Path(kb.vault_path).expanduser().resolve()
    full = (vault / raw).resolve()
    try:
        full.relative_to(vault)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes vault") from exc
    if not full.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return {
        "rel_path": raw,
        "local_path": str(full),
        "vault_path": str(vault),
        "exists": True,
    }


@app.post("/api/v1/notes/{note_id}/ingest")
async def ingest_existing_note(
    note_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """
    Trigger (or re-trigger) ingestion for an existing note.
    Always force-reingests — resets processed/failed flags so the pipeline runs
    regardless of prior ingestion status.
    """
    require_ai()
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()

    if not note:
        return {"error": "Note not found"}, 404

    # Reset flags so the pipeline treats this as a fresh ingestion.
    note.processed = False
    note.failed = False
    note.processing_stage = "Queued for ingestion"
    note.processing_model = None
    await db.commit()

    note_data = NoteInput(
        content=note_body(note, kb),
        created_at=note.created_at.isoformat() if note.created_at else None,
        title=(note.title or "").strip() or None,
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
    if not note_data.skip_ingestion:
        require_ai()
    note_id = str(uuid.uuid4())
    c_at = (
        _parse_date_str(note_data.created_at)
        if note_data.created_at
        else datetime.now(timezone.utc)
    )

    new_note = Note(
        id=note_id,
        content="",
        created_at=c_at,
        processed=False,
        processing_stage=(
            "Queued for ingestion" if not note_data.skip_ingestion else "Saved"
        ),
        kb_id=kb.kb_id,
    )
    persist_note_body(new_note, kb, note_data.content or "")
    db.add(new_note)
    await db.flush()
    await refresh_note_links(db, kb.kb_id, note_id, note_data.content or "")
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
    sync_vault: bool = True,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """
    Get notes for the active KB, sorted by creation date (newest first).
    Optionally filter by processed/failed status.
    """
    if sync_vault:
        from app.services.vault_sync import sync_vault_notes

        try:
            await sync_vault_notes(db, kb)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[get_notes] vault sync skipped: {exc}")

    base_query = select(Note)

    filters = [Note.kb_id == kb.kb_id]
    if search:
        term = f"%{search}%"
        # Bodies live in vault files — search title + rel_path metadata only
        filters.append((Note.title.ilike(term)) | (Note.rel_path.ilike(term)))

    if processed is not None:
        filters.append(Note.processed == processed)

    if failed is not None:
        filters.append(Note.failed == failed)

    base_query = base_query.where(*filters)
    query = base_query.order_by(Note.created_at.desc())
    result = await db.execute(query)
    notes = result.scalars().all()
    return [_note_response(n, kb) for n in notes]


@app.get("/api/v1/notes/{note_id}")
async def get_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Get a specific note by ID with vault-backed content."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()

    if not note:
        return {"error": "Note not found"}
    return _note_response(note, kb)


@app.get("/api/v1/notes/{note_id}/status")
async def get_note_ingestion_status(note_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the ingestion status of a note without fetching its full content.
    Useful for polling after triggering background ingestion.

    Returns:
      - processed: true once ingestion completes successfully
      - failed: true if the ingestion pipeline encountered a permanent error
      - status: "completed" | "failed" | "processing"
      - processing_stage: user-facing current stage
      - processing_model: model/service currently in use, if any
    """
    try:
        result = await db.execute(
            select(
                Note.id,
                Note.processed,
                Note.failed,
                Note.processing_stage,
                Note.processing_model,
            ).where(Note.id == note_id)
        )
        row = result.one_or_none()
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503, detail="Database temporarily unavailable, retry shortly"
        ) from exc

    if row is None:
        return {"error": "Note not found"}, 404

    note_id, processed, failed, processing_stage, processing_model = row
    if processed:
        status = "completed"
    elif failed:
        status = "failed"
    else:
        status = "processing"

    return {
        "id": note_id,
        "processed": processed,
        "failed": failed,
        "status": status,
        "processing_stage": processing_stage,
        "processing_model": processing_model,
    }


@app.put("/api/v1/notes/{note_id}")
async def update_note(
    note_id: str,
    note_input: CreateNoteInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """
    Update an existing note's vault file content.
    Does NOT trigger re-ingestion or change processed status.
    Use POST /api/v1/notes/{id}/ingest to re-ingest after updating.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    existing_note = result.scalar_one_or_none()

    if not existing_note:
        return {"error": "Note not found"}

    persist_note_body(
        existing_note,
        kb,
        note_input.content or "",
        title=(note_input.title or "").strip() or None,
    )

    if note_input.created_at:
        existing_note.created_at = _parse_date_str(note_input.created_at)

    existing_note.updated_at = datetime.now(timezone.utc)
    # Autosave must never start ingestion. Clear watcher false-positives while
    # leaving a user-queued ingest stage alone.
    stage = existing_note.processing_stage or ""
    if not existing_note.processed and not (
        stage.startswith("Queued") or stage.startswith("Starting")
    ):
        if (
            "pending" in stage.lower()
            or stage.startswith("External")
            or stage.startswith("Changed on disk")
            or not stage
        ):
            existing_note.processing_stage = "Saved"

    await refresh_note_links(db, kb.kb_id, note_id, note_input.content or "")

    await db.commit()
    await db.refresh(existing_note)

    return _note_response(existing_note, kb)


@app.delete("/api/v1/notes/{note_id}")
async def delete_note(
    note_id: str, db: AsyncSession = Depends(get_db), kb: KBContext = Depends(get_kb)
):
    """
    Delete a note from SQLite + vault .md, then best-effort graph/vector cleanup.

    Vault file + DB row are removed first so a graph failure cannot leave an
    orphan markdown file or a broken UI still pointing at a deleted note.
    """
    return await _delete_note_impl(note_id, db, kb)


class BatchDeleteNotesInput(BaseModel):
    """Body for batch note deletion."""

    ids: list[str]


@app.post("/api/v1/notes/batch-delete")
async def batch_delete_notes(
    body: BatchDeleteNotesInput,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Delete many notes in the current KB (vault + SQLite + graph cleanup)."""
    ids = [i.strip() for i in (body.ids or []) if i and i.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="ids must not be empty")
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="At most 100 notes per batch")

    deleted: list[str] = []
    failed: list[dict] = []
    for note_id in ids:
        try:
            await _delete_note_impl(note_id, db, kb)
            deleted.append(note_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("[batch-delete] Failed for %s: %s", note_id, exc)
            failed.append({"id": note_id, "error": str(exc)})

    return {
        "deleted": deleted,
        "failed": failed,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
    }


async def _delete_note_impl(
    note_id: str, db: AsyncSession, kb: KBContext
) -> dict:
    """Shared single-note delete used by DELETE and batch-delete."""
    import re as _re
    from pathlib import Path as _Path

    from app.utils.bucket_storage import delete_files as _delete_files

    note_row = await db.execute(
        select(Note).where(Note.id == note_id, Note.kb_id == kb.kb_id)
    )
    note_obj = note_row.scalar_one_or_none()
    if not note_obj:
        # Idempotent — already gone from DB; still try to clear a matching vault file.
        return {
            "status": "deleted",
            "id": note_id,
            "orphans_removed": 0,
            "already_gone": True,
        }

    body = note_body(note_obj, kb) if note_obj else ""
    rel_path = note_obj.rel_path
    _file_url_re = _re.compile(
        r"\[(?:📎|🎤)[^\]]*\]\((https?://[^)]+|/(?:files|uploads|vault-files)/[^)]+)\)"
    )
    attached_file_keys: list[str] = []
    if body:
        for _m in _file_url_re.finditer(body):
            _url = _m.group(1).rstrip("/")
            _key = _url.split("/")[-1]
            if _key:
                attached_file_keys.append(_key)

    vault = _Path(kb.vault_path) if kb.vault_path else None
    if vault and rel_path:
        try:
            delete_note_file(vault, rel_path)
            logger.info(f"[delete_note] Removed vault file {vault / rel_path}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[delete_note] Vault file delete failed ({rel_path}): {exc}")
            try:
                target = vault / rel_path
                if target.exists():
                    target.unlink(missing_ok=True)
            except Exception as exc2:  # pylint: disable=broad-exception-caught
                logger.error(f"[delete_note] Vault file still present: {exc2}")

    await db.execute(
        delete(NoteLink).where(
            NoteLink.kb_id == kb.kb_id,
            or_(
                NoteLink.source_note_id == note_id,
                NoteLink.target_note_id == note_id,
            ),
        )
    )
    await db.execute(delete(Note).where(Note.id == note_id, Note.kb_id == kb.kb_id))
    await db.commit()

    orphan_ids: list[str] = []
    try:
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
        orphan_ids = [r["entity_id"] for r in (rows or []) if r.get("entity_id")]
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(f"[delete_note] Graph orphan query failed: {exc}")

    try:
        kb.graph.execute_query(
            "MATCH (n:Node {id: $id}) WHERE n.kind = 'note' DETACH DELETE n",
            {"id": note_id},
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(f"[delete_note] Graph note delete failed: {exc}")

    for entity_id in orphan_ids:
        try:
            kb.graph.execute_query(
                "MATCH (n:Node {id: $id}) DETACH DELETE n",
                {"id": entity_id},
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass
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

    if settings.STORAGE_BACKEND == "s3":
        for key in attached_file_keys:
            try:
                await _delete_files(key)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    else:
        from app.services.local_storage import remove_upload

        for key in attached_file_keys:
            try:
                if vault:
                    await remove_upload(vault, key)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    if attached_file_keys:
        logger.info(
            f"[delete_note] Deleted {len(attached_file_keys)} attached file(s) for note {note_id}."
        )

    return {"status": "deleted", "id": note_id, "orphans_removed": len(orphan_ids)}


# --- Admin ---


@app.get("/api/v1/admin/maintenance-status")
async def get_maintenance_status(kb: KBContext = Depends(get_kb)):
    """Return the running state of background maintenance jobs."""
    return kb.get_ingestion_workflow().get_maintenance_status()


@app.post("/api/v1/admin/rebuild-communities")
async def rebuild_communities(
    background_tasks: BackgroundTasks, kb: KBContext = Depends(get_kb)
):
    """
    Trigger a full Leiden community detection pass in the background.

    Useful when community detection was cancelled or never ran after ingestion.
    The job runs asynchronously; poll the server logs for progress.
    COMMUNITY_DETECTION_ENABLED only controls the automatic post-ingestion trigger;
    this manual endpoint is always available.
    """
    background_tasks.add_task(kb.get_ingestion_workflow().rebuild_leiden_communities)
    return {
        "status": "started",
        "message": "Leiden community recompute triggered. Check server logs for progress.",
    }


class TemporalDigestInput(BaseModel):
    """Optional request body for the temporal digest build endpoint."""

    period: str | None = (
        None  # "month" | "week" | "year" — defaults to TEMPORAL_DIGEST_PERIOD
    )


@app.post("/api/v1/admin/build-temporal-digests")
async def build_temporal_digests(
    background_tasks: BackgroundTasks,
    body: TemporalDigestInput = TemporalDigestInput(),
    kb: KBContext = Depends(get_kb),
):
    """
    Trigger a temporal digest build in the background.

    Groups all ``isolated_context`` chunks that carry a ``note_created_at`` date
    by the requested time period, summarises each bucket with the LLM, and stores
    the results as ``temporal_digest`` nodes in the knowledge graph.
    TEMPORAL_DIGESTS_ENABLED only controls the automatic post-ingestion trigger;
    this manual endpoint is always available.
    """
    from app.core.config import settings as _settings

    _period = body.period or _settings.TEMPORAL_DIGEST_PERIOD
    background_tasks.add_task(
        kb.get_ingestion_workflow().build_temporal_digests, _period
    )
    return {
        "status": "started",
        "message": f"Temporal digest build triggered (period={_period}). Check server logs for progress.",
    }


@app.post("/api/v1/admin/reset-ingestion-data")
async def reset_ingestion_data(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """
    Wipe all ingestion data for the current KB and mark every note as unprocessed.

    Clears the Kuzu graph, Qdrant vector collections, and Typesense search index
    for this KB, then resets ``processed`` and ``failed`` flags on all notes so
    they are eligible for re-ingestion.  The store wipes run as a background task;
    the Postgres reset is committed before the response is returned.
    """
    # Reset note flags immediately so the caller sees the correct state right away.
    await db.execute(
        update(Note).where(Note.kb_id == kb.kb_id).values(processed=False, failed=False)
    )
    await db.commit()

    # Wipe vector/graph/search stores in the background (sync service calls).
    def _wipe_stores() -> None:
        node_count = kb.graph.wipe_all_nodes()
        logger.info(f"[Admin] reset-ingestion-data: wiped {node_count} graph nodes")
        kb.qdrant.reset_all()
        kb.typesense.reset_all()
        logger.info("[Admin] reset-ingestion-data: all stores cleared")

    background_tasks.add_task(_wipe_stores)
    return {
        "status": "started",
        "message": "Ingestion data cleared. Notes marked as unprocessed. Store wipes running in background.",
    }


@app.post("/api/v1/admin/reingest-all")
async def reingest_all(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """Queue notes in the current KB for ingestion (reads vault .md bodies)."""
    require_ai()
    result = await db.execute(
        select(Note)
        .where(Note.kb_id == kb.kb_id)
        .where(
            (Note.processed == False) | (Note.failed == True)  # noqa: E712
        )
    )
    notes = result.scalars().all()

    wf = kb.get_ingestion_workflow()
    for note in notes:
        note_data = NoteInput(
            content=note_body(note, kb),
            created_at=note.created_at.isoformat() if note.created_at else None,
            title=note.title,
        )
        background_tasks.add_task(wf.process_note, note_data, note.id)

    logger.info(f"[Admin] reingest-all: queued {len(notes)} notes for KB '{kb.kb_id}'")
    return {
        "status": "queued",
        "notes_queued": len(notes),
        "message": f"Queued {len(notes)} notes for ingestion.",
    }


# ---------------------------------------------------------------------------
# Knowledge-base management
# ---------------------------------------------------------------------------


class CreateKBInput(BaseModel):
    """Request body for creating a new knowledge base."""

    name: str
    vault_path: str | None = None


class RenameKBInput(BaseModel):
    """Request body for renaming a knowledge base."""

    name: str


class DeleteKBInput(BaseModel):
    """Legacy optional flags — product path always wipes vault + indexes."""

    delete_vault_files: bool = True
    wipe_indexes: bool = True


@app.get("/api/v1/kb")
async def list_knowledge_bases():
    """List all registered knowledge bases."""
    return {"knowledge_bases": kb_registry.list_kbs()}


@app.post("/api/v1/kb", status_code=201)
async def create_knowledge_base(body: CreateKBInput):
    """Create a new knowledge base with its own notes vault folder.

    Does not re-run Setup — models / data dirs stay shared. Provision separate
    Kuzu/Qdrant/Meili stores for the new KB.
    """
    if not body.name or not body.name.strip():
        raise HTTPException(
            status_code=400, detail="Knowledge base name must not be empty"
        )
    vault = (body.vault_path or "").strip()
    if not vault:
        raise HTTPException(
            status_code=400,
            detail="vault_path is required — choose where markdown notes for this KB are saved",
        )
    try:
        ctx = kb_registry.create_kb(body.name.strip(), vault_path=vault)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to create knowledge base '%s'", body.name)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create knowledge base: {exc}",
        ) from exc
    return {
        "id": ctx.kb_id,
        "name": ctx.name,
        "vault_path": ctx.vault_path,
        "message": f"Knowledge base '{ctx.name}' created. Use ?kb={ctx.name} to target it.",
    }


async def _purge_kb_sql_notes(db: AsyncSession, kb_id: str) -> int:
    """Delete all SQLite notes and note_links for a KB. Returns note count."""
    result = await db.execute(select(Note.id).where(Note.kb_id == kb_id))
    ids = [row[0] for row in result.all()]
    await db.execute(delete(NoteLink).where(NoteLink.kb_id == kb_id))
    await db.execute(delete(Note).where(Note.kb_id == kb_id))
    await db.commit()
    return len(ids)


@app.post("/api/v1/kb/empty")
async def empty_knowledge_base(
    db: AsyncSession = Depends(get_db),
    kb: KBContext = Depends(get_kb),
):
    """
    Full wipe of the current KB while keeping the KB registry row.

    Always deletes notes, vault contents, graph/search indexes, and Firefly admin.
    """
    vault_path = kb.vault_path or ""
    try:
        await firefly_service.destroy_kb_administration(kb)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[empty-kb] Firefly destroy failed: %s", exc)

    notes_removed = await _purge_kb_sql_notes(db, kb.kb_id)

    try:
        kb.graph.wipe_all_nodes()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[empty-kb] Graph wipe failed: %s", exc)
    try:
        kb.qdrant.reset_all()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[empty-kb] Qdrant reset failed: %s", exc)
    try:
        kb.typesense.reset_all()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("[empty-kb] Meili reset failed: %s", exc)

    if vault_path:
        try:
            clear_vault_contents(vault_path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("[empty-kb] Vault clear failed: %s", exc)
            try:
                ensure_vault(vault_path)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    return {
        "status": "emptied",
        "kb_id": kb.kb_id,
        "name": kb.name,
        "notes_removed": notes_removed,
        "vault_path": vault_path,
        "message": (
            f"Emptied knowledge base '{kb.name}': notes, vault files, indexes, "
            "and Firefly administration removed. The KB itself remains."
        ),
    }


@app.post("/api/v1/kb/delete-non-default")
async def delete_all_non_default_knowledge_bases(
    db: AsyncSession = Depends(get_db),
):
    """Fully wipe and unregister every knowledge base except ``default``."""
    kbs = kb_registry.list_kbs()
    removed: list[dict] = []
    errors: list[dict] = []
    for entry in kbs:
        kid = entry.get("id")
        if not kid or kid == "default":
            continue
        try:
            meta = kb_registry.get_metadata(kid)
            ctx = kb_registry.get_kb(kid)
            if ctx is not None:
                try:
                    await firefly_service.destroy_kb_administration(ctx)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        "[delete-non-default] Firefly destroy failed for %s: %s",
                        kid,
                        exc,
                    )
            await _purge_kb_sql_notes(db, kid)
            kb_registry.delete_kb(kid, delete_vault_files=True, wipe_indexes=True)
            removed.append(
                {
                    "id": kid,
                    "name": entry.get("name"),
                    "vault_path": (meta or {}).get("vault_path"),
                }
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors.append({"id": kid, "error": str(exc)})

    return {
        "removed": removed,
        "errors": errors,
        "removed_count": len(removed),
        "message": f"Deleted {len(removed)} knowledge base(s). Default KB was kept.",
    }


@app.delete("/api/v1/kb/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete a non-default knowledge base.

    Always destroys Firefly admin, SQLite notes, vault folder, and indexes.
    """
    if kb_id == "default":
        raise HTTPException(
            status_code=400, detail="The default knowledge base cannot be deleted"
        )
    meta = kb_registry.get_metadata(kb_id)
    if not meta:
        raise HTTPException(
            status_code=404, detail=f"Knowledge base '{kb_id}' not found"
        )

    ctx = kb_registry.get_kb(kb_id)
    if ctx is not None:
        try:
            await firefly_service.destroy_kb_administration(ctx)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("[delete-kb] Firefly destroy failed: %s", exc)

    await _purge_kb_sql_notes(db, kb_id)

    deleted = kb_registry.delete_kb(
        kb_id,
        delete_vault_files=True,
        wipe_indexes=True,
    )
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Knowledge base '{kb_id}' not found"
        )
    try:
        await firefly_service.sync_kb_group_title(kb_id, name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Firefly group title sync failed after KB rename: %s", exc)
    return {"id": kb_id, "name": name}
