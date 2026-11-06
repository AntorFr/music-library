"""
Frontend (HTML) view routes, one module per family of pages.

Renders Jinja2 templates for the Music Library web UI.
All JSON API calls are delegated to the existing /api/v1/ routes.

``router`` is the single router the application mounts. Registration order
matters for the static media routes (``/media/new`` before ``/media/{media_id}``):
``media`` registers both in that order, ahead of the sub-resources.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.views import browse, listen, media, media_items, settings
from app.api.views.shared import OWNER_COOKIE, templates

router = APIRouter(tags=["frontend"])
router.include_router(listen.router)
router.include_router(media.router)
router.include_router(media_items.router)
router.include_router(settings.router)
router.include_router(browse.router)

__all__ = ["OWNER_COOKIE", "router", "templates"]
