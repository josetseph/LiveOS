"""Standalone local-models service: Florence, Whisper, PDF, reranker."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from inference import engine

app = FastAPI(title="LiveOS Local Models Service")


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)
    top_n: int | None = None


class UnloadRequest(BaseModel):
    family: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/image/describe")
async def describe_image(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "image.png").suffix or ".png"
    tmp_path = await _save_upload(file, suffix)
    try:
        started = time.perf_counter()
        text = await run_in_threadpool(engine.describe_image_path, tmp_path)
        return {"text": text, "elapsed_seconds": time.perf_counter() - started}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _safe_remove(tmp_path)


@app.post("/audio/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    tmp_path = await _save_upload(file, suffix)
    try:
        started = time.perf_counter()
        text = await run_in_threadpool(engine.transcribe_audio_path, tmp_path)
        return {"text": text, "elapsed_seconds": time.perf_counter() - started}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _safe_remove(tmp_path)


@app.post("/pdf/extract")
async def extract_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"
    tmp_path = await _save_upload(file, suffix)
    try:
        started = time.perf_counter()
        text = await run_in_threadpool(engine.extract_pdf_path, tmp_path)
        return {"text": text, "elapsed_seconds": time.perf_counter() - started}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _safe_remove(tmp_path)


@app.post("/rerank")
async def rerank(request: RerankRequest) -> dict[str, Any]:
    if not request.documents:
        return {"results": []}
    try:
        started = time.perf_counter()
        results = await run_in_threadpool(
            engine.rerank,
            request.query,
            request.documents,
            request.top_n,
        )
        return {
            "results": results,
            "elapsed_seconds": time.perf_counter() - started,
        }
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/unload")
async def unload(request: UnloadRequest) -> dict[str, Any]:
    try:
        return await run_in_threadpool(engine.unload, request.family)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _save_upload(file: UploadFile, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
    return tmp_path


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
