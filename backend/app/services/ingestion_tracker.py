"""Ingestion tracking for idle-timeout community recomputation."""

import asyncio
import threading
from datetime import datetime
from typing import Callable

from app.core.log import get_logger

logger = get_logger("IngestionTracker")

# Trigger Leiden recompute this many seconds after ALL ingestions have completed.
COMMUNITY_IDLE_SECONDS = 120 # 2 minutes


class IngestionTrackerService:
    """
    Tracks ingestions and triggers a full Leiden recompute 5 minutes after the last ingestion.
    If a new ingestion arrives while community detection is in progress, the running recompute
    is signalled to stop early so the system prioritises ingestion throughput.
    """

    def __init__(self):
        self.last_ingestion_time: datetime | None = None
        self._pending_node_ids: set[str] = set()
        self._community_recompute_running = False
        # Set when a run is interrupted mid-way so the next trigger doesn't skip
        # "No pending nodes" even though communities are only partially built.
        self._recompute_needed = False
        # Tracks how many ingestion pipelines are currently running. The
        # community timer must NEVER start while this is > 0.
        self._active_ingestion_count: int = 0
        self._lock = asyncio.Lock()
        self._debounce_task: asyncio.Task | None = None
        # Threading event used to signal a running rebuild to stop between clusters.
        self.cancel_recompute: threading.Event = threading.Event()

    def mark_ingestion_complete(self):
        """Record the completion time of the latest ingestion."""
        self.last_ingestion_time = datetime.now()
        logger.info(
            f"[IngestionTracker] Ingestion completed at {self.last_ingestion_time}"
        )

    def has_active_ingestions(self) -> bool:
        """Thread-safe enough read helper for worker threads."""
        return self._active_ingestion_count > 0

    async def begin_ingestion(self) -> None:
        """
        Call at the START of every ingestion pipeline.
        Increments the active-ingestion counter and cancels any pending
        community-recompute timer so it can never fire while work is in progress.
        """
        async with self._lock:
            self._active_ingestion_count += 1
            active = self._active_ingestion_count
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
                self._debounce_task = None

            # Immediate preemption signal: request cancellation as soon as ingestion starts
            # so any in-flight recompute path can stop cooperatively.
            self.cancel_recompute.set()

            # Keep a specific info log when tracker-known recompute is running.
            recompute_running = self._community_recompute_running
        logger.info(
            f"[IngestionTracker] Ingestion started — active: {active}, community timer cancelled"
        )
        if recompute_running:
            logger.info(
                "[IngestionTracker] Ingestion started while recompute is running — "
                "signalling immediate cancellation."
            )

    async def end_ingestion(self, callback: Callable) -> None:
        """
        Call at the END of every ingestion pipeline (success or failure).
        Decrements the active counter; when it reaches 0 starts the
        {COMMUNITY_IDLE_SECONDS}s idle timer for community recompute.
        """
        async with self._lock:
            self._active_ingestion_count = max(0, self._active_ingestion_count - 1)
            active = self._active_ingestion_count
        logger.info(f"[IngestionTracker] Ingestion ended — active: {active}")
        if active == 0 and not self._community_recompute_running:
            logger.info(
                f"[IngestionTracker] All ingestions complete — starting "
                f"{COMMUNITY_IDLE_SECONDS}s idle timer for community recompute"
            )
            self.schedule_recompute(callback)

    async def queue_nodes_for_community_recompute(
        self, node_ids: list[str]
    ) -> tuple[list[str], int]:
        """
        Queue node IDs for the next idle-triggered recompute.
        If a recompute is already running, signal it to cancel so ingestion takes priority.
        Always returns an empty batch (caller uses schedule_recompute instead).
        """
        normalized_ids = {node_id for node_id in node_ids if node_id}
        async with self._lock:
            self._pending_node_ids.update(normalized_ids)
            self._recompute_needed = True
            queue_size = len(self._pending_node_ids)
            if self._community_recompute_running:
                logger.info(
                    "[IngestionTracker] Ingestion arrived while recompute is running — "
                    "signalling recompute to cancel (will restart after next idle period)."
                )
                self.cancel_recompute.set()
        logger.info(
            f"[IngestionTracker] Queued {len(normalized_ids)} nodes "
            f"(total pending: {queue_size})"
        )
        return [], queue_size

    def schedule_recompute(self, callback: Callable) -> None:
        """Debounce: cancel any existing timer and start a fresh COMMUNITY_IDLE_SECONDS countdown."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            logger.info(
                f"[IngestionTracker] Recompute timer reset "
                f"({COMMUNITY_IDLE_SECONDS}s idle trigger)"
            )
        else:
            logger.info(
                f"[IngestionTracker] Recompute timer started "
                f"({COMMUNITY_IDLE_SECONDS}s idle trigger)"
            )
        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(self._debounce_recompute(callback))
        except RuntimeError:
            logger.warning(
                "[IngestionTracker] No running event loop; recompute timer not started."
            )

    async def _debounce_recompute(self, callback: Callable) -> None:
        try:
            await asyncio.sleep(COMMUNITY_IDLE_SECONDS)
        except asyncio.CancelledError:
            return

        async with self._lock:
            if self._community_recompute_running:
                logger.info(
                    "[IngestionTracker] Recompute already running; skipping debounce trigger."
                )
                return
            if not self._pending_node_ids and not self._recompute_needed:
                logger.info(
                    "[IngestionTracker] No pending nodes after idle wait; skipping recompute."
                )
                return
            self._community_recompute_running = True
            self._recompute_needed = False
            queue_size = len(self._pending_node_ids)
            self._pending_node_ids.clear()

        # Clear any previous cancellation signal before starting the new run.
        self.cancel_recompute.clear()

        logger.info(
            f"[IngestionTracker] Community recompute triggered after "
            f"{COMMUNITY_IDLE_SECONDS}s idle: {queue_size} pending nodes"
        )
        cancelled_early = False
        try:
            await asyncio.to_thread(callback)
        except Exception as e:
            logger.error(
                f"[IngestionTracker] Leiden recompute failed: {e}", exc_info=True
            )
        else:
            cancelled_early = self.cancel_recompute.is_set()
        finally:
            await self.mark_community_recompute_complete()

        if cancelled_early:
            # Mark that communities are only partially built so the next debounce
            # trigger doesn't skip the "no pending nodes" gate.
            async with self._lock:
                self._recompute_needed = True
                should_reschedule = self._active_ingestion_count == 0
            if should_reschedule:
                logger.info(
                    f"[IngestionTracker] Recompute exited early; no active ingestions — "
                    f"rescheduling full rebuild in {COMMUNITY_IDLE_SECONDS}s."
                )
                self.schedule_recompute(callback)
            else:
                logger.info(
                    "[IngestionTracker] Recompute exited early; ingestion still active — "
                    "timer will start when last ingestion ends."
                )

    async def mark_community_recompute_complete(self):
        async with self._lock:
            self._community_recompute_running = False

    async def force_similarity_detection(self):
        """Compatibility no-op; similarity detection remains reactive."""
        logger.info(
            "[IngestionTracker] force_similarity_detection called — "
            "similarity detection is now reactive per-node, no batch run needed"
        )


# Global singleton
ingestion_tracker = IngestionTrackerService()
