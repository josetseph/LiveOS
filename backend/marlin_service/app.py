"""Standalone Marlin video-captioning service."""

from __future__ import annotations

import gc
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

os.environ.setdefault("FORCE_QWENVL_VIDEO_READER", "pyav")
os.environ.setdefault("VIDEO_MAX_PIXELS", "200704")
os.environ.setdefault("FPS", "2.0")
os.environ.setdefault("FPS_MAX_FRAMES", "240")
os.environ.setdefault("FPS_MIN_FRAMES", "4")

MODEL_PATH = Path(os.getenv("MARLIN_MODEL_PATH", "/models/marlin-2b"))

app = FastAPI(title="LiveOS Marlin Service")

_model: Any | None = None
_model_lock = threading.Lock()


def _patch_video_decoder() -> None:
    """Force transformers video processing to use pyav in CPU containers."""
    from transformers.video_processing_utils import BaseVideoProcessor
    from transformers.video_utils import load_video

    def _fetch_videos_pyav(self, video_url_or_urls, sample_indices_fn=None):
        if isinstance(video_url_or_urls, list):
            return list(
                zip(
                    *[
                        self.fetch_videos(x, sample_indices_fn=sample_indices_fn)
                        for x in video_url_or_urls
                    ]
                )
            )
        return load_video(
            video_url_or_urls, backend="pyav", sample_indices_fn=sample_indices_fn
        )

    BaseVideoProcessor.fetch_videos = _fetch_videos_pyav


def _load_model():
    """Load Marlin once per service process."""
    global _model  # pylint: disable=global-statement

    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        if not MODEL_PATH.is_dir():
            raise RuntimeError(f"Marlin model directory not found: {MODEL_PATH}")

        _patch_video_decoder()

        import torch
        from transformers import AutoModelForCausalLM

        from inference_device import (
            prepare_qwen3_5_inference,
            resolve_torch_device,
            resolve_torch_dtype,
        )

        device = resolve_torch_device()
        dtype = resolve_torch_dtype(device)
        prepare_qwen3_5_inference(device)
        started = time.perf_counter()
        print(
            f"Loading Marlin from {MODEL_PATH} on {device} ({dtype})...",
            flush=True,
        )
        _model = (
            AutoModelForCausalLM.from_pretrained(
                str(MODEL_PATH),
                trust_remote_code=True,
                dtype=dtype,
                low_cpu_mem_usage=True,
            )
            .to(device)
            .eval()
        )
        print(f"Loaded Marlin in {time.perf_counter() - started:.1f}s", flush=True)
        return _model


def _unload_model() -> dict[str, bool]:
    """Release Marlin model memory until the next caption request."""
    global _model  # pylint: disable=global-statement

    with _model_lock:
        _model = None
        gc.collect()
    return {"loaded": False}


@app.get("/health")
def health() -> dict[str, str]:
    """Health endpoint for Docker and backend checks."""
    return {"status": "ok"}


def _caption_path(path: str) -> dict[str, Any]:
    """Run Marlin captioning for a local video path."""
    model = _load_model()
    started = time.perf_counter()
    result = model.caption(path)
    elapsed = time.perf_counter() - started
    return {
        "scene": result.get("scene", ""),
        "events": result.get("events", []),
        "elapsed_seconds": elapsed,
    }


@app.post("/caption")
async def caption(file: UploadFile = File(...)) -> dict[str, Any]:
    """Caption an uploaded video with Marlin."""
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)

    try:
        return await run_in_threadpool(_caption_path, tmp_path)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


@app.post("/unload")
async def unload() -> dict[str, bool]:
    """Unload Marlin after a video batch completes."""
    return await run_in_threadpool(_unload_model)
