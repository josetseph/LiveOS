"""Knowledge Base registry: create, cache, and resolve per-KB service contexts."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.config import REPO_ROOT, settings
from app.core.log import get_logger
from app.services.graph import GraphService, graph_service
from app.services.qdrant_service import QdrantService, qdrant_service
from app.services.retrieval import RetrievalService
from app.services.typesense_service import TypesenseService, typesense_service
from app.workflows.chat import ChatWorkflow
from app.workflows.ingestion import IngestionWorkflow

logger = get_logger("KBRegistry")

# Path where KB metadata is persisted between restarts.
_REGISTRY_FILE = REPO_ROOT / "data" / "kb_registry.json"

# Well-known ID for the default (original) knowledge base.
DEFAULT_KB_ID = "default"


@dataclass
class KBContext:
    """Bundled service instances for one knowledge base."""

    kb_id: str
    name: str
    graph: GraphService
    qdrant: QdrantService
    typesense: TypesenseService
    # Lazy-initialized — set by registry after construction.
    retrieval_service: object = field(default=None, repr=False)
    ingestion_workflow: object = field(default=None, repr=False)
    chat_workflow: object = field(default=None, repr=False)

    def _ensure_lazy(self) -> None:
        """Initialize retrieval_service, ingestion_workflow, and chat_workflow on first access."""
        if self.retrieval_service is None:
            self.retrieval_service = RetrievalService(
                graph=self.graph,
                qdrant=self.qdrant,
                typesense=self.typesense,
            )
        if self.ingestion_workflow is None:
            self.ingestion_workflow = IngestionWorkflow(
                graph=self.graph,
                qdrant=self.qdrant,
                typesense=self.typesense,
            )
        if self.chat_workflow is None:
            self.chat_workflow = ChatWorkflow(retrieval=self.retrieval_service)

    def get_retrieval_service(self):
        """Return the lazily initialised RetrievalService for this KB."""
        self._ensure_lazy()
        return self.retrieval_service

    def get_ingestion_workflow(self):
        """Return the lazily initialised IngestionWorkflow for this KB."""
        self._ensure_lazy()
        return self.ingestion_workflow

    def get_chat_workflow(self):
        """Return the lazily initialised ChatWorkflow for this KB."""
        self._ensure_lazy()
        return self.chat_workflow


def _default_kb() -> KBContext:
    """Return a KBContext wrapping the global default singletons."""
    ctx = KBContext(
        kb_id=DEFAULT_KB_ID,
        name="default",
        graph=graph_service,
        qdrant=qdrant_service,
        typesense=typesense_service,
    )
    return ctx


class KBRegistry:
    """Manages knowledge base metadata and caches live KBContext instances."""

    def __init__(self) -> None:
        self._lock = (
            threading.RLock()
        )  # reentrant — get_kb_by_name calls get_kb under the same lock
        self._metadata: dict[str, dict] = {}  # kb_id → {id, name, kuzu_path, ...}
        self._cache: dict[str, KBContext] = {}  # kb_id → live context
        self._load()
        # Always ensure the default KB exists in memory (not necessarily persisted).
        if DEFAULT_KB_ID not in self._cache:
            self._cache[DEFAULT_KB_ID] = _default_kb()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load KB metadata from the registry JSON file."""
        if not _REGISTRY_FILE.exists():
            return
        try:
            with open(_REGISTRY_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("knowledge_bases", []):
                self._metadata[entry["id"]] = entry
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[KBRegistry] Failed to load registry: {exc}")

    def _save(self) -> None:
        """Persist current KB metadata to the registry JSON file."""
        try:
            _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"knowledge_bases": list(self._metadata.values())},
                    f,
                    indent=2,
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[KBRegistry] Failed to save registry: {exc}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def list_kbs(self) -> list[dict]:
        """Return metadata for all registered KBs (including the default)."""
        with self._lock:
            defaults = [
                {
                    "id": DEFAULT_KB_ID,
                    "name": "default",
                    "kuzu_path": str(settings.KUZU_DB_PATH),
                    "qdrant_collection_prefix": settings.QDRANT_COLLECTION_NODE_CORES.rsplit(
                        "_", 1
                    )[
                        0
                    ],
                    "typesense_collection": settings.TYPESENSE_COLLECTION_NAME,
                    "created_at": None,
                }
            ]
            named = list(self._metadata.values())
            return defaults + named

    def create_kb(self, name: str) -> KBContext:
        """Create a new knowledge base and return its initialized KBContext.

        Collections are named ``<name>_node_cores``, ``<name>_node_relationships``,
        ``<name>_node_isolated_contexts``, and ``<name>_nodes`` (Typesense).
        Kuzu database lives at ``data/kuzu/<name>``.
        """
        slug = name.lower().replace(" ", "_")
        kb_id = str(uuid.uuid4())

        kuzu_path = str(REPO_ROOT / "data" / "kuzu" / slug)
        col_prefix = slug

        meta = {
            "id": kb_id,
            "name": name,
            "slug": slug,
            "kuzu_path": kuzu_path,
            "qdrant_col_cores": f"{col_prefix}_node_cores",
            "qdrant_col_rels": f"{col_prefix}_node_relationships",
            "qdrant_col_contexts": f"{col_prefix}_node_isolated_contexts",
            "typesense_collection": f"{col_prefix}_nodes",
            "created_at": datetime.utcnow().isoformat(),
        }

        with self._lock:
            self._metadata[kb_id] = meta
            self._save()
            ctx = self._build_context(kb_id, meta)
            self._cache[kb_id] = ctx

        logger.info(f"[KBRegistry] Created KB '{name}' (id={kb_id})")
        return ctx

    def get_kb(self, kb_id: str) -> KBContext | None:
        """Return the KBContext for the given id, or None if not found."""
        with self._lock:
            if kb_id in self._cache:
                return self._cache[kb_id]
            if kb_id not in self._metadata:
                return None
            ctx = self._build_context(kb_id, self._metadata[kb_id])
            self._cache[kb_id] = ctx
            return ctx

    def get_kb_by_name(self, name: str) -> KBContext | None:
        """Resolve a KB by name or slug (case-insensitive). Returns default KB if name is 'default'."""
        normalized = name.lower().strip()
        if normalized in ("default", ""):
            return self._cache[DEFAULT_KB_ID]
        with self._lock:
            for kb_id, meta in self._metadata.items():
                if (
                    meta.get("name", "").lower() == normalized
                    or meta.get("slug", "") == normalized
                ):
                    return self.get_kb(kb_id)
        return None

    def delete_kb(self, kb_id: str) -> bool:
        """Delete a KB, dropping its Qdrant collections, Typesense collection, and Kuzu directory.

        Returns True on success, False if the KB was not found.
        The default KB cannot be deleted.
        """
        if kb_id == DEFAULT_KB_ID:
            raise ValueError("The default knowledge base cannot be deleted.")

        with self._lock:
            meta = self._metadata.pop(kb_id, None)
            self._cache.pop(kb_id, None)
            if meta is None:
                return False
            self._save()

        # Best-effort cleanup — log but do not raise on partial failures.
        self._cleanup_stores(meta)
        logger.info(f"[KBRegistry] Deleted KB '{meta['name']}' (id={kb_id})")
        return True

    def rename_kb(self, kb_id: str, new_name: str) -> bool:
        """Rename a KB. The slug and UUID are unchanged; only the display name is updated.

        Returns True on success, False if the KB was not found.
        The default KB cannot be renamed.
        """
        if kb_id == DEFAULT_KB_ID:
            raise ValueError("The default knowledge base cannot be renamed.")
        with self._lock:
            if kb_id not in self._metadata:
                return False
            self._metadata[kb_id]["name"] = new_name
            self._save()
            if kb_id in self._cache:
                self._cache[kb_id].name = new_name
        logger.info(f"[KBRegistry] Renamed KB {kb_id} → '{new_name}'")
        return True

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_context(self, kb_id: str, meta: dict) -> KBContext:
        """Instantiate a fresh KBContext from stored metadata."""
        qdrant = QdrantService(
            col_cores=meta["qdrant_col_cores"],
            col_relationships=meta["qdrant_col_rels"],
            col_contexts=meta["qdrant_col_contexts"],
        )
        ts = TypesenseService(collection_name=meta["typesense_collection"])
        graph = GraphService(db_path=meta["kuzu_path"], qdrant=qdrant)
        return KBContext(
            kb_id=kb_id,
            name=meta["name"],
            graph=graph,
            qdrant=qdrant,
            typesense=ts,
        )

    def _cleanup_stores(self, meta: dict) -> None:
        """Drop Qdrant collections, Typesense collection, and Kuzu directory."""
        # Qdrant
        try:
            qs = QdrantService(
                col_cores=meta["qdrant_col_cores"],
                col_relationships=meta["qdrant_col_rels"],
                col_contexts=meta["qdrant_col_contexts"],
            )
            if qs.is_available() and qs.client:
                for col in [
                    meta["qdrant_col_cores"],
                    meta["qdrant_col_rels"],
                    meta["qdrant_col_contexts"],
                ]:
                    try:
                        qs.client.delete_collection(col)
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[KBRegistry] Qdrant cleanup failed: {exc}")

        # Typesense
        try:
            ts = TypesenseService(collection_name=meta["typesense_collection"])
            if ts.is_available() and ts.client:
                try:
                    ts.client.collections[meta["typesense_collection"]].delete()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[KBRegistry] Typesense cleanup failed: {exc}")

        # Kuzu — remove directory tree
        try:
            kuzu_path = Path(meta["kuzu_path"])
            if kuzu_path.exists() and kuzu_path.is_dir():
                shutil.rmtree(kuzu_path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"[KBRegistry] Kuzu cleanup failed: {exc}")


# Module-level singleton
kb_registry = KBRegistry()
