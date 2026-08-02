"""Sync note_links table from note markdown wikilinks."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.note import Note
from app.models.wikilink import NoteLink
from app.services.kb_registry import KBContext
from app.services.note_files import note_body
from app.services.vault import extract_wikilinks


def _note_lookup(notes: list[Note]) -> dict[str, str]:
    """Map common wikilink target forms → note id."""
    by_title: dict[str, str] = {}
    for n in notes:
        if n.title:
            by_title.setdefault(n.title.lower().strip(), n.id)
        if n.rel_path:
            rel = n.rel_path.replace("\\", "/")
            stem = Path(rel).stem.lower()
            by_title.setdefault(stem, n.id)
            without_ext = rel[:-3] if rel.lower().endswith(".md") else rel
            by_title.setdefault(without_ext.lower(), n.id)
            by_title.setdefault(Path(rel).name.lower().replace(".md", ""), n.id)
    return by_title


def _resolve_target(by_title: dict[str, str], key: str) -> str | None:
    if key in by_title:
        return by_title[key]
    # Obsidian-style path without extension
    alt = key[:-3] if key.endswith(".md") else key
    if alt in by_title:
        return by_title[alt]
    # Match by basename only
    base = Path(key).name.lower().replace(".md", "")
    return by_title.get(base)


def _apply_note_links(
    *,
    kb_id: str,
    source_note_id: str,
    content: str,
    notes: list[Note],
    clear_existing,
    add_link,
) -> None:
    clear_existing()
    links = extract_wikilinks(content)
    if not links:
        return

    by_title = _note_lookup(notes)

    seen: set[str] = set()
    for target_title, _alias in links:
        key = target_title.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        add_link(target_title, _resolve_target(by_title, key))


async def refresh_note_links(
    db: AsyncSession,
    kb_id: str,
    source_note_id: str,
    content: str,
) -> None:
    """Replace all outgoing wikilinks for a note."""
    result = await db.execute(select(Note).where(Note.kb_id == kb_id))
    notes = list(result.scalars().all())

    await db.execute(
        delete(NoteLink).where(
            NoteLink.kb_id == kb_id,
            NoteLink.source_note_id == source_note_id,
        )
    )
    links = extract_wikilinks(content)
    if not links:
        return
    by_title = _note_lookup(notes)
    seen: set[str] = set()
    for target_title, _alias in links:
        key = target_title.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        db.add(
            NoteLink(
                kb_id=kb_id,
                source_note_id=source_note_id,
                target_title=target_title,
                target_note_id=_resolve_target(by_title, key),
            )
        )


def refresh_note_links_sync(
    session: Session,
    kb_id: str,
    source_note_id: str,
    content: str,
) -> None:
    """Sync variant for vault watcher / non-async contexts."""
    notes = list(session.execute(select(Note).where(Note.kb_id == kb_id)).scalars().all())

    def clear_existing() -> None:
        session.execute(
            delete(NoteLink).where(
                NoteLink.kb_id == kb_id,
                NoteLink.source_note_id == source_note_id,
            )
        )

    def add_link(target_title: str, target_note_id: str | None) -> None:
        session.add(
            NoteLink(
                kb_id=kb_id,
                source_note_id=source_note_id,
                target_title=target_title,
                target_note_id=target_note_id,
            )
        )

    _apply_note_links(
        kb_id=kb_id,
        source_note_id=source_note_id,
        content=content,
        notes=notes,
        clear_existing=clear_existing,
        add_link=add_link,
    )


async def rebuild_kb_note_links(db: AsyncSession, kb: KBContext) -> dict[str, int]:
    """Re-parse every note body (vault-backed) into note_links."""
    notes = list(
        (await db.execute(select(Note).where(Note.kb_id == kb.kb_id))).scalars().all()
    )
    for note in notes:
        content = note_body(note, kb)
        await refresh_note_links(db, kb.kb_id, note.id, content)
    await db.commit()
    link_count = len(
        list(
            (
                await db.execute(select(NoteLink).where(NoteLink.kb_id == kb.kb_id))
            ).scalars().all()
        )
    )
    return {"notes": len(notes), "links": link_count}


async def notes_graph_payload(db: AsyncSession, kb_id: str) -> dict:
    """Nodes + edges for notes-only graph view."""
    notes = list(
        (await db.execute(select(Note).where(Note.kb_id == kb_id))).scalars().all()
    )
    links = list(
        (await db.execute(select(NoteLink).where(NoteLink.kb_id == kb_id))).scalars().all()
    )
    nodes = [
        {
            "id": n.id,
            "title": n.title or n.rel_path or n.id,
            "type": "note",
            "rel_path": n.rel_path,
        }
        for n in notes
    ]
    known = {n.id for n in notes}
    for link in links:
        if not link.target_note_id:
            phantom_id = f"missing:{link.target_title}"
            if phantom_id not in known:
                nodes.append(
                    {
                        "id": phantom_id,
                        "title": link.target_title,
                        "type": "missing",
                        "rel_path": None,
                    }
                )
                known.add(phantom_id)

    edges = []
    for link in links:
        tid = link.target_note_id or f"missing:{link.target_title}"
        edges.append(
            {
                "source": link.source_note_id,
                "target": tid,
                "type": "wikilink",
            }
        )
    return {"nodes": nodes, "edges": edges}


async def note_neighborhood_payload(
    db: AsyncSession,
    kb_id: str,
    note_id: str,
) -> dict:
    """Local graph: selected note + direct wikilink neighbors."""
    full = await notes_graph_payload(db, kb_id)
    neighbor_ids = {note_id}
    for edge in full["edges"]:
        if edge["source"] == note_id:
            neighbor_ids.add(edge["target"])
        if edge["target"] == note_id:
            neighbor_ids.add(edge["source"])
    nodes = [n for n in full["nodes"] if n["id"] in neighbor_ids]
    edges = [
        e
        for e in full["edges"]
        if e["source"] in neighbor_ids and e["target"] in neighbor_ids
    ]
    return {"nodes": nodes, "edges": edges, "center_id": note_id}
