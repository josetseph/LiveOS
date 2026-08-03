"""Vault filesystem helpers — human-titled .md notes + attachments."""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]")

# Paths Orb just wrote — vault watcher should ignore briefly so in-app saves
# are not treated as external edits.
_recent_self_writes: dict[str, float] = {}
_SELF_WRITE_TTL_SEC = 12.0


def mark_self_write(vault: Path, rel_path: str) -> None:
    key = str((vault / rel_path).resolve())
    _recent_self_writes[key] = time.time()
    # Opportunistic cleanup
    cutoff = time.time() - (_SELF_WRITE_TTL_SEC * 3)
    stale = [k for k, t in _recent_self_writes.items() if t < cutoff]
    for k in stale:
        _recent_self_writes.pop(k, None)


def is_recent_self_write(path: str | Path) -> bool:
    try:
        key = str(Path(path).resolve())
    except OSError:
        return False
    ts = _recent_self_writes.get(key)
    if ts is None:
        return False
    return (time.time() - ts) < _SELF_WRITE_TTL_SEC


def sanitize_title(title: str) -> str:
    """Make a filesystem-safe note title."""
    t = (title or "Untitled").strip() or "Untitled"
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", t)
    t = t.rstrip(". ")
    return t[:180] or "Untitled"


def unique_md_path(vault: Path, title: str, folder: str | None = None) -> Path:
    """Return vault-relative path for a new note with human title.

    ``folder`` is an optional vault-relative directory (e.g. ``Life/Daily Log``).
    """
    base = sanitize_title(title)
    folder_clean = (folder or "").replace("\\", "/").strip("/")
    # Reject escaping the vault
    if ".." in folder_clean.split("/"):
        folder_clean = ""
    prefix = f"{folder_clean}/" if folder_clean else ""
    candidate = f"{prefix}{base}.md"
    n = 2
    while (vault / candidate).exists():
        candidate = f"{prefix}{base} {n}.md"
        n += 1
    return Path(candidate)


def read_note_file(vault: Path, rel_path: str) -> str:
    from app.services.vault_ops import safe_vault_join

    path = safe_vault_join(Path(vault), rel_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_note_file(vault: Path, rel_path: str, content: str) -> None:
    from app.services.vault_ops import safe_vault_join

    path = safe_vault_join(Path(vault), rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mark_self_write(vault, rel_path)
    path.write_text(content, encoding="utf-8")


def delete_note_file(vault: Path | str, rel_path: str | None) -> None:
    if not rel_path:
        return
    from app.services.vault_ops import safe_vault_join

    path = safe_vault_join(Path(vault), rel_path)
    if path.exists():
        path.unlink()


def extract_wikilinks(content: str) -> list[tuple[str, str | None]]:
    """Return list of (target_title, alias)."""
    out: list[tuple[str, str | None]] = []
    for m in WIKILINK_RE.finditer(content or ""):
        target = m.group(1).strip()
        alias = m.group(2).strip() if m.group(2) else None
        if target:
            out.append((target, alias))
    return out


def title_from_filename(rel_path: str) -> str:
    return Path(rel_path).stem


def _faststart_mp4(path: Path) -> None:
    """Move moov atom to the front so HTML5 video can play without full download.

    No-op if ffmpeg is missing or the file is not an MP4/MOV container.
    """
    if path.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        return
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=path.suffix, delete=False, dir=path.parent
        ) as tmp:
            tmp_path = Path(tmp.name)
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(tmp_path),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode == 0 and tmp_path.is_file() and tmp_path.stat().st_size > 0:
            tmp_path.replace(path)
            tmp_path = None
    except Exception:
        pass
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def save_attachment(vault: Path, src_name: str, data: bytes, folder: str | None = None) -> str:
    """Write bytes under vault folder (default ``attachments/``).

    Filename keeps the original stem and appends a short id for uniqueness:
    ``logo-a1b2c3d4.png``.
    """
    folder_clean = (folder or "attachments").replace("\\", "/").strip("/")
    if not folder_clean or ".." in folder_clean.split("/"):
        folder_clean = "attachments"
    dest_dir = vault / folder_clean
    dest_dir.mkdir(parents=True, exist_ok=True)

    src = Path(src_name or "file")
    stem = sanitize_title(src.stem or "file")[:120]
    ext = src.suffix.lower() if src.suffix else ""
    short = uuid.uuid4().hex[:8]
    name = f"{stem}-{short}{ext}"
    # Extremely unlikely collision, but stay safe
    n = 2
    while (dest_dir / name).exists():
        name = f"{stem}-{short}-{n}{ext}"
        n += 1
    path = dest_dir / name
    path.write_bytes(data)
    _faststart_mp4(path)
    return f"{folder_clean}/{name}"



def ensure_vault(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    (p / "attachments").mkdir(exist_ok=True)
    return p


def clear_vault_contents(path: str | Path) -> None:
    """Remove all files/folders under a vault, then recreate the empty layout."""
    p = Path(path).expanduser().resolve()
    if p.exists():
        for child in list(p.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    ensure_vault(p)
