"""AI setup gating — block chat/ingest/entity enrichment when AI is not configured."""

from __future__ import annotations

from fastapi import HTTPException

from app.core.config import settings


def ai_is_configured() -> bool:
    mode = (settings.AI_SETUP_MODE or "none").lower().strip()
    if mode in ("none", "", "skip"):
        return False
    if mode == "local":
        # Local is only "configured" once chat+embed GGUFs are on disk.
        try:
            from app.services.local_models import gguf_paths_if_present

            return gguf_paths_if_present() is not None
        except Exception:  # pylint: disable=broad-exception-caught
            return False
    if mode in ("cloud", "hybrid"):
        # Cloud/hybrid needs at least one provider key or custom OpenAI-compat URL
        if settings.OPENAI_API_KEY or settings.GEMINI_API_KEY or settings.ANTHROPIC_API_KEY:
            return True
        if settings.LLM_PROVIDER not in ("local", "ollama", "lm_studio", "none"):
            return True
        if settings.LLM_BASE_URL and settings.LLM_API_KEY and settings.LLM_API_KEY not in (
            "lm-studio",
            "ollama",
            "",
        ):
            return True
        return bool(settings.LLM_BASE_URL)
    return False


def require_ai() -> None:
    """Raise 503 if AI features are unavailable (Obsidian-like limited mode)."""
    if not ai_is_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "ai_not_configured",
                "message": (
                    "AI is not configured. Notes, wikilinks, and finance still work. "
                    "Open Setup to enable local models or a cloud provider."
                ),
            },
        )
