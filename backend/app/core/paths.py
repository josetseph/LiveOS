"""Resolve Orb data / models / vault paths from env and paths.json."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Avoid importing settings here (circular with config.py)
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

_PATHS_CACHE: dict | None = None


def _default_app_support() -> Path:
    """OS-specific Application Support / AppData directory for Orb.

    Prefers Orb; falls back to LifeOS / LiveOS if those already have paths.json.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        candidates = [base / "Orb", base / "LifeOS", base / "LiveOS"]
    elif sys.platform == "win32":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(root)
        candidates = [base / "Orb", base / "LifeOS", base / "LiveOS"]
    else:
        base = Path.home() / ".config"
        candidates = [base / "Orb", base / "LifeOS", base / "LiveOS"]
    for candidate in candidates:
        if (candidate / "paths.json").exists():
            return candidate
    return candidates[0]


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def paths_json_location() -> Path:
    """Bootstrap file that only stores data_dir / models_dir / default_vault_path."""
    override = _env_first("ORB_PATHS_FILE", "LIVEOS_PATHS_FILE")
    if override:
        return Path(override)
    return _default_app_support() / "paths.json"


def load_paths_file() -> dict:
    """Load paths.json if present."""
    global _PATHS_CACHE  # noqa: PLW0603
    if _PATHS_CACHE is not None:
        return _PATHS_CACHE
    loc = paths_json_location()
    if loc.exists():
        try:
            _PATHS_CACHE = json.loads(loc.read_text(encoding="utf-8"))
            return _PATHS_CACHE
        except (OSError, json.JSONDecodeError):
            pass
    _PATHS_CACHE = {}
    return _PATHS_CACHE


def save_paths_file(
    data_dir: str | Path,
    models_dir: str | Path,
    default_vault_path: str | Path | None = None,
    ai_setup_mode: str | None = None,
) -> Path:
    """Write bootstrap paths.json and clear cache.

    If ``default_vault_path`` / ``ai_setup_mode`` are omitted, keep any existing
    values so a later Setup save does not wipe them.
    """
    global _PATHS_CACHE  # noqa: PLW0603
    loc = paths_json_location()
    loc.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if loc.exists():
        try:
            existing = json.loads(loc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    payload = {
        "data_dir": str(Path(data_dir).expanduser().resolve()),
        "models_dir": str(Path(models_dir).expanduser().resolve()),
    }
    vault = default_vault_path if default_vault_path is not None else existing.get(
        "default_vault_path"
    )
    if vault:
        payload["default_vault_path"] = str(Path(str(vault)).expanduser().resolve())
    mode = ai_setup_mode if ai_setup_mode is not None else existing.get("ai_setup_mode")
    if mode:
        payload["ai_setup_mode"] = mode
    loc.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _PATHS_CACHE = payload
    return loc


def resolve_data_dir() -> Path:
    """DATA_DIR: env > paths.json > repo data/ (dev fallback)."""
    env = _env_first("ORB_DATA_DIR", "LIVEOS_DATA_DIR", "DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    file_paths = load_paths_file()
    if file_paths.get("data_dir"):
        return Path(file_paths["data_dir"]).expanduser().resolve()
    return (REPO_ROOT / "data").resolve()


def resolve_models_dir() -> Path:
    """MODELS_DIR: env > paths.json > backend/models (dev fallback)."""
    env = _env_first("ORB_MODELS_DIR", "LIVEOS_MODELS_DIR", "MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    file_paths = load_paths_file()
    if file_paths.get("models_dir"):
        return Path(file_paths["models_dir"]).expanduser().resolve()
    return (BACKEND_DIR / "models").resolve()


def resolve_default_vault_path() -> Path | None:
    file_paths = load_paths_file()
    if file_paths.get("default_vault_path"):
        return Path(file_paths["default_vault_path"]).expanduser().resolve()
    env = _env_first("ORB_DEFAULT_VAULT", "LIVEOS_DEFAULT_VAULT")
    if env:
        return Path(env).expanduser().resolve()
    return None


def looks_like_network_volume(path: Path | str) -> bool:
    """True for typical NAS / external mounts under /Volumes (not system disk)."""
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        resolved = str(path)
    if sys.platform == "darwin" and resolved.startswith("/Volumes/"):
        local_roots = ("/Volumes/Macintosh HD", "/Volumes/Macintosh HD Data")
        return not any(resolved.startswith(r) for r in local_roots)
    # Linux network mounts often under /mnt or /media
    if sys.platform.startswith("linux"):
        return resolved.startswith(("/mnt/", "/media/", "/run/user/"))
    return False


def local_download_staging_dir() -> Path:
    """Local SSD cache for downloads that will later be moved to MODELS_DIR.

    Hugging Face + large GGUF downloads are unreliable directly onto SMB/NAS;
    we stage here then copy/move to the user's chosen models directory.
    """
    override = _env_first(
        "ORB_HF_STAGING",
        "ORB_DOWNLOAD_STAGING",
        "LIVEOS_HF_STAGING",
        "LIVEOS_DOWNLOAD_STAGING",
    )
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Caches" / "Orb" / "model-downloads"
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / "Orb" / "model-downloads"
    else:
        p = Path.home() / ".cache" / "orb" / "model-downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_data_layout(data_dir: Path | None = None) -> Path:
    """Create standard DATA_DIR subdirectories."""
    root = data_dir or resolve_data_dir()
    for sub in (
        "kuzu",
        "qdrant",
        "meilisearch",
        "typesense",  # legacy path kept for migration
        "logs",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def sqlite_url(data_dir: Path | None = None) -> str:
    root = data_dir or resolve_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    db_path = (root / "orb.db").resolve()
    return f"sqlite+aiosqlite:///{db_path}"
