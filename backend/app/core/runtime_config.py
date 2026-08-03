"""Persistent runtime configuration overrides.

Stored under DATA_DIR/runtime_config.json (desktop) with a repo data/ fallback.
API keys are never stored here — those stay in ``.env``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.core.config import BACKEND_DIR, settings
from app.core.log import get_logger

logger = get_logger("RuntimeConfig")

_lock = threading.Lock()

MUTABLE_KEYS: frozenset[str] = frozenset(
    {"provider", "model", "ingestion_model", "base_url", "ai_setup_mode"}
)


def _data_path() -> Path:
    try:
        from app.core.paths import resolve_data_dir

        return resolve_data_dir() / "runtime_config.json"
    except Exception:  # pylint: disable=broad-exception-caught
        return BACKEND_DIR.parent / "data" / "runtime_config.json"


def load() -> dict:
    """Return saved overrides from disk, or ``{}`` if none exist."""
    path = _data_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if k in MUTABLE_KEYS}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load runtime config: %s", exc)
    return {}


def save(overrides: dict) -> None:
    """Persist overrides to disk (only allowed keys are written)."""
    safe = {k: v for k, v in overrides.items() if k in MUTABLE_KEYS}
    path = _data_path()
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save runtime config: %s", exc)


def apply_to_settings(overrides: dict) -> None:
    """Mutate the global ``settings`` object with the given overrides."""
    if "provider" in overrides and overrides["provider"] is not None:
        settings.LLM_PROVIDER = overrides["provider"]
    if "model" in overrides and overrides["model"] is not None:
        settings.CHAT_MODEL = overrides["model"]
    if "ingestion_model" in overrides and overrides["ingestion_model"] is not None:
        settings.INGESTION_MODEL = overrides["ingestion_model"]
    if "base_url" in overrides and overrides["base_url"] is not None:
        settings.LLM_BASE_URL = overrides["base_url"]
    if "ai_setup_mode" in overrides and overrides["ai_setup_mode"] is not None:
        settings.AI_SETUP_MODE = overrides["ai_setup_mode"]
