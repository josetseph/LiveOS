"""
tavily_service.py — Web search fallback via Tavily API.

Called by retrieval.py when FALLBACK_MODE="web" and the local knowledge graph
could not produce a satisfactory answer. Results are returned as context dicts
in the same shape as local retrieval docs so the synthesis step is unchanged.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("TavilyService")


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web via Tavily and return results as retrieval-compatible dicts.

    Each returned dict has the same shape as a local retrieval doc:
      {
        "text": "<snippet used as context>",
        "type": "web_search",
        "original_obj": {"name": "<title>", "entity_type": "WebResult", ...},
        "priority": "fallback",
        "vector_score": 0.0,
        "final_score": 0.0,
        "linked_notes": [],
      }

    Returns an empty list if TAVILY_API_KEY is not set or the API call fails.
    """
    if not settings.TAVILY_API_KEY:
        logger.warning("[Tavily] TAVILY_API_KEY not set — skipping web search.")
        return []

    try:
        from tavily import TavilyClient  # type: ignore[import]
    except ImportError:
        logger.error("[Tavily] tavily-python package not installed. Run: pip install tavily-python")
        return []

    try:
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
        )
        results: list[dict] = response.get("results", [])
        logger.info(f"[Tavily] Web search returned {len(results)} result(s) for: {query!r}")
    except Exception as exc:
        logger.warning(f"[Tavily] Web search failed: {exc}")
        return []

    docs: list[dict] = []
    for r in results:
        title = r.get("title", "Web Result")
        url = r.get("url", "")
        content = r.get("content", "")
        snippet = content[:800] if content else title

        docs.append(
            {
                "text": f"{title}: {snippet}",
                "type": "web_search",
                "original_obj": {
                    "name": title,
                    "entity_type": "WebResult",
                    "description": snippet,
                    "url": url,
                },
                "priority": "fallback",
                "is_recent": False,
                "vector_score": 0.0,
                "rerank_score": 0.0,
                "final_score": 0.0,
                "boosts": {},
                "linked_notes": [],
            }
        )

    return docs
