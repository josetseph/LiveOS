"""Helpers to load/save note bodies from the vault."""

from __future__ import annotations

from pathlib import Path

from app.models.note import Note
from app.services.kb_registry import KBContext
from app.services.vault import (
    read_note_file,
    unique_md_path,
    write_note_file,
)


def note_body(note: Note, kb: KBContext) -> str:
    if note.rel_path and kb.vault_path:
        text = read_note_file(Path(kb.vault_path), note.rel_path)
        if text or note.rel_path:
            return normalize_vault_file_refs(text)
    return normalize_vault_file_refs(note.content or "")


def normalize_vault_file_refs(content: str) -> str:
    """Collapse accidental ``attachments/attachments/`` in vault-file URLs."""
    if not content:
        return content or ""
    import re

    return re.sub(
        r"(/vault-files/[^/\s)]+/)attachments/attachments/",
        r"\1attachments/",
        content,
    )


def persist_note_body(
    note: Note,
    kb: KBContext,
    content: str,
    title: str | None = None,
    folder: str | None = None,
) -> None:
    vault = Path(kb.vault_path)
    vault.mkdir(parents=True, exist_ok=True)
    content = normalize_vault_file_refs(content or "")
    display_title = (title if title is not None else note.title) or ""
    if not note.rel_path:
        filename_title = display_title or "Untitled"
        note.rel_path = str(unique_md_path(vault, filename_title, folder=folder))
    if title is not None:
        note.title = display_title or None
    elif display_title and display_title != note.title:
        note.title = display_title
    write_note_file(vault, note.rel_path, content or "")
    # Keep nullable content empty — body is file-backed
    note.content = ""
