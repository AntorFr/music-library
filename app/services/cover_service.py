"""
Cover art service — download, resize, and cache cover images.

Provides stable local URLs for ESPHome and the frontend.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


def _ensure_covers_dir() -> Path:
    """Create the covers directory if it doesn't exist."""
    covers = settings.covers_dir
    covers.mkdir(parents=True, exist_ok=True)
    return covers


async def download_and_save_cover(
    media_id: str,
    image_url: str,
    size: int | None = None,
) -> str | None:
    """
    Download an image from URL, resize it, and save locally.

    Args:
        media_id: The local media ID (used as filename).
        image_url: Source URL of the image.
        size: Target square size in px (default from settings).

    Returns:
        Local relative path like "covers/{media_id}.jpg" or None on failure.
    """
    size = size or settings.cover_max_size
    covers_dir = _ensure_covers_dir()
    local_path = covers_dir / f"{media_id}.jpg"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            raw_bytes = resp.content
    except httpx.HTTPError as exc:
        logger.warning("Failed to download cover from %s: %s", image_url, exc)
        return None

    try:
        img = Image.open(BytesIO(raw_bytes))
        img = img.convert("RGB")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        img.save(local_path, "JPEG", quality=85, optimize=True)
        logger.info("Saved cover for media %s → %s", media_id, local_path)
        return f"covers/{media_id}.jpg"
    except Exception as exc:
        logger.warning("Failed to process cover image: %s", exc)
        return None


async def save_cover_from_bytes(
    media_id: str,
    image_bytes: bytes,
    size: int | None = None,
) -> str | None:
    """
    Save uploaded image bytes as a cover.

    Args:
        media_id: The local media ID.
        image_bytes: Raw image bytes.
        size: Target square size in px.

    Returns:
        Local relative path or None.
    """
    size = size or settings.cover_max_size
    covers_dir = _ensure_covers_dir()
    local_path = covers_dir / f"{media_id}.jpg"

    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        img.save(local_path, "JPEG", quality=85, optimize=True)
        return f"covers/{media_id}.jpg"
    except Exception as exc:
        logger.warning("Failed to process uploaded cover: %s", exc)
        return None


def get_cover_path(media_id: str) -> Path | None:
    """Return the local file path for a cover if it exists."""
    path = settings.covers_dir / f"{media_id}.jpg"
    return path if path.exists() else None


async def ensure_local_cover(media_id: str, cover_url: str | None) -> str | None:
    """
    Ensure a local cover file exists for the given media.

    If the local file is missing but cover_url is available,
    re-download and cache it. Returns the local relative path
    or None if no cover is available.
    """
    # Already exists locally?
    if get_cover_path(media_id):
        return f"covers/{media_id}.jpg"

    # No source URL — nothing we can do
    if not cover_url:
        return None

    logger.info("Re-downloading missing cover for media %s", media_id)
    return await download_and_save_cover(media_id, cover_url)


def delete_cover(media_id: str) -> None:
    """Delete the locally cached cover for a media item."""
    path = settings.covers_dir / f"{media_id}.jpg"
    if path.exists():
        path.unlink()
        logger.info("Deleted cover for media %s", media_id)
