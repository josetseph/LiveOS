"""Local vault attachment storage (replaces RustFS for desktop)."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.vault import save_attachment


_ATTACH_RE = re.compile(
    r"(?:!\[([^\]]*)\]\(([^)]+)\)|\[(?:📎|🎤)\s*([^\]]+)\]\(([^)]+)\))"
)


def extract_attachment_refs(content: str) -> list[tuple[str, str]]:
    """Return (label, url_or_path) pairs from note markdown (📎/🎤 and image embeds)."""
    out: list[tuple[str, str]] = []
    for m in _ATTACH_RE.finditer(content or ""):
        if m.group(2):
            out.append(((m.group(1) or "").strip() or "image", m.group(2)))
        else:
            out.append((m.group(3), m.group(4)))
    return out


def vault_rel_from_url(url: str) -> str | None:
    """Map /vault-files/<kb>/path → path, or pass through vault-relative paths."""
    if not url:
        return None
    cleaned = url.replace("\\", "/")
    if cleaned.startswith("/vault-files/"):
        parts = cleaned.split("/", 3)  # '', vault-files, kb, rest
        return parts[3] if len(parts) > 3 else None
    if cleaned.startswith("attachments/"):
        return cleaned
    marker = "/attachments/"
    if marker in cleaned:
        return "attachments/" + cleaned.split(marker, 1)[1].split("?")[0]
    return None


async def store_upload(vault: Path, filename: str, data: bytes, kb_id: str) -> dict:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "attachments").mkdir(parents=True, exist_ok=True)
    rel = save_attachment(vault, filename, data)
    url = f"/vault-files/{kb_id}/{rel}"
    return {"url": url, "key": rel, "filename": filename}


async def remove_upload(vault: Path, key_or_url: str) -> None:
    rel = vault_rel_from_url(key_or_url) or key_or_url
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return
    path = vault / rel
    if path.is_file():
        path.unlink()
