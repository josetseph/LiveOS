"""Liveness / root endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.log import get_logger

logger = get_logger("API")
router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint returning a simple service-status greeting."""
    logger.debug("Health check hit")
    return {"message": "Orb is online", "status": "active"}


@router.get("/health")
async def health_check():
    """Lightweight liveness probe for the desktop supervisor (no KB/graph deps)."""
    return {"status": "healthy"}
