"""System / health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import settings
from app.services.music_assistant import MusicAssistantClient, get_ma_client

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/health/ma")
async def health_ma(ma: MusicAssistantClient = Depends(get_ma_client)):
    """Check Music Assistant connectivity."""
    connected = ma.connected
    server_info = ma._server_info if connected else None
    return {
        "status": "ok" if connected else "disconnected",
        "music_assistant_url": settings.music_assistant_url,
        "server_version": server_info.get("server_version") if server_info else None,
        "schema_version": server_info.get("schema_version") if server_info else None,
    }
