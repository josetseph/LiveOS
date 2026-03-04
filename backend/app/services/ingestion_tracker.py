"""
Ingestion Tracking Service - Monitors ingestion completion.

Alias detection is now handled reactively per-node during _update_node_summary
via _check_node_aliases. No batch scheduling is needed.
"""

import asyncio
from datetime import datetime
from app.core.log import get_logger

logger = get_logger("IngestionTracker")


class IngestionTrackerService:
    """Tracks ingestion completions (alias detection is now reactive, not batched)"""

    def __init__(self):
        self.last_ingestion_time: datetime | None = None

    def mark_ingestion_complete(self):
        """
        Called after each ingestion completes.
        Alias detection runs reactively per-node inside _update_node_summary,
        so no batch scheduling is needed here.
        """
        self.last_ingestion_time = datetime.now()
        logger.info(
            f"[IngestionTracker] Ingestion completed at {self.last_ingestion_time}"
        )

    async def force_alias_detection(self):
        """
        No-op: alias detection is now reactive (runs per-node during ingestion).
        Kept for API compatibility.
        """
        logger.info(
            "[IngestionTracker] force_alias_detection called — "
            "alias detection is now reactive per-node, no batch run needed"
        )


# Global singleton
ingestion_tracker = IngestionTrackerService()
