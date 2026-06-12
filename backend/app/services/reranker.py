"""HTTP client for the local Qwen reranker service."""

from __future__ import annotations

from typing import Optional

import httpx
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("RerankerService")


class RerankerService:  # pylint: disable=too-few-public-methods
    """Proxy reranking requests to the local-models service."""

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
    ) -> list[dict]:
        if not documents:
            return []

        if not settings.LOCAL_MODELS_SERVICE_URL:
            logger.warning("[Reranker] Local models service is disabled")
            return []

        url = f"{settings.LOCAL_MODELS_SERVICE_URL.rstrip('/')}/rerank"
        payload = {"query": query, "documents": documents, "top_n": top_n}
        timeout = httpx.Timeout(settings.LOCAL_MODELS_SERVICE_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(f"[Reranker] Service call failed: {exc}")
            return []


reranker_service = RerankerService()
