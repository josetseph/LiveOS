"""Persistent runtime configuration overrides.

Allows the chat LLM provider, model, and base URL to be changed at runtime
via the API without restarting the server. Overrides are persisted to
``data/runtime_config.json`` (relative to the repo root) so they survive
restarts. API keys are never stored here — those stay in ``.env``.
"""

import json
import threading
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.core.log import get_logger

logger = get_logger("RuntimeConfig")

_DATA_PATH = BACKEND_DIR.parent / "data" / "runtime_config.json"
_lock = threading.Lock()

# Only these keys may be overridden at runtime
MUTABLE_KEYS: frozenset[str] = frozenset(
    {"provider", "model", "ingestion_model", "base_url"}
)


def load() -> dict:
    """Return saved overrides from disk, or ``{}`` if none exist."""
    try:
        if _DATA_PATH.exists():
            return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load runtime config", extra={"error": str(exc)})
    return {}


def save(overrides: dict) -> None:
    """Persist overrides to disk (only allowed keys are written)."""
    safe = {k: v for k, v in overrides.items() if k in MUTABLE_KEYS}
    with _lock:
        try:
            _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            _DATA_PATH.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not save runtime config", extra={"error": str(exc)})


def apply_to_settings(overrides: dict) -> None:
    """Mutate the global ``settings`` object with the given overrides.

    * ``provider``        → ``settings.LLM_PROVIDER``
    * ``model``           → ``settings.CHAT_MODEL``  (highest-priority chat model key)
    * ``ingestion_model`` → ``settings.INGESTION_MODEL``  (highest-priority ingestion model key)
    * ``base_url``        → ``settings.LLM_BASE_URL``
    """
    from app.core.config import settings  # local import to avoid circular

    if "provider" in overrides:
        settings.LLM_PROVIDER = overrides["provider"]
    if "model" in overrides:
        settings.CHAT_MODEL = overrides["model"]
    if "ingestion_model" in overrides:
        settings.INGESTION_MODEL = overrides["ingestion_model"]
    if "base_url" in overrides:
        settings.LLM_BASE_URL = overrides["base_url"]
