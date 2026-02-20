"""
Ingestion Tracking Service - Monitors ingestion completion and schedules alias detection.

Tracks when ingestions complete and automatically schedules alias detection batch jobs
with debouncing (if new ingestion happens, resets the timer).
"""

import asyncio
from datetime import datetime, timedelta
from app.core.log import get_logger

logger = get_logger("IngestionTracker")


class IngestionTrackerService:
    """Tracks ingestion completions and schedules alias detection"""

    def __init__(self):
        self.last_ingestion_time: datetime | None = None
        self.alias_detection_delay = timedelta(
            minutes=5
        )  # Wait 5 min after last ingestion
        self.scheduled_task: asyncio.Task | None = None
        self.is_alias_detection_running = False

    def mark_ingestion_complete(self):
        """
        Called after each ingestion completes.
        Resets the timer for alias detection (debouncing).
        """
        self.last_ingestion_time = datetime.now()
        logger.info(
            f"[IngestionTracker] Ingestion completed at {self.last_ingestion_time}"
        )

        # Cancel existing scheduled task (debounce)
        if self.scheduled_task and not self.scheduled_task.done():
            logger.info(
                "[IngestionTracker] Cancelling previous scheduled alias detection (debounce)"
            )
            self.scheduled_task.cancel()

        # Schedule new alias detection
        self.scheduled_task = asyncio.create_task(self._schedule_alias_detection())

    async def _schedule_alias_detection(self):
        """
        Waits for the delay period, then runs alias detection.
        If another ingestion happens during wait, this gets cancelled.
        """
        try:
            delay_seconds = self.alias_detection_delay.total_seconds()
            logger.info(
                f"[IngestionTracker] Alias detection scheduled in {delay_seconds/60:.1f} minutes"
            )

            await asyncio.sleep(delay_seconds)

            # Check if we're still the most recent scheduled task
            if self.is_alias_detection_running:
                logger.info(
                    "[IngestionTracker] Alias detection already running, skipping"
                )
                return

            # Run alias detection
            logger.info("[IngestionTracker] Starting auto-scheduled alias detection")
            await self._run_alias_detection()

        except asyncio.CancelledError:
            logger.info(
                "[IngestionTracker] Alias detection cancelled (new ingestion occurred)"
            )
        except Exception as e:
            logger.error(f"[IngestionTracker] Error in scheduled alias detection: {e}")

    async def _run_alias_detection(self):
        """Run the alias detection batch job"""
        from app.services.alias_detector import alias_detector

        self.is_alias_detection_running = True

        try:
            # Run batch detection (limit to 50 entities per auto-run to avoid overwhelming system)
            stats = await alias_detector.batch_detect_aliases(limit=50)

            logger.info(
                f"[IngestionTracker] Alias detection complete: "
                f"{stats['links_created']} links created from {stats['processed']} entities"
            )

        except Exception as e:
            logger.error(f"[IngestionTracker] Alias detection failed: {e}")
        finally:
            self.is_alias_detection_running = False

    async def force_alias_detection(self):
        """
        Manually trigger alias detection (for testing or manual runs).
        Bypasses debouncing.
        """
        logger.info("[IngestionTracker] Manual alias detection triggered")
        await self._run_alias_detection()


# Global singleton
ingestion_tracker = IngestionTrackerService()
