"""
Cover art service — download, resize, and cache cover images.

Provides stable local URLs for ESPHome and the frontend.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)

# Key used to sign thumbnail proxy URLs (see `sign_thumb`). A configured secret keeps links
# valid across restarts; otherwise a random per-process key is fine — the cache is ephemeral
# and links are regenerated each session. Resolved once at import (stable within a process,
# and shared by every app served from that process).
_THUMB_KEY = (settings.thumb_signing_key or secrets.token_hex(32)).encode("utf-8")


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
        clear_resized(media_id)  # base changed -> drop stale resized variants
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
        clear_resized(media_id)  # base changed -> drop stale resized variants
        return f"covers/{media_id}.jpg"
    except Exception as exc:
        logger.warning("Failed to process uploaded cover: %s", exc)
        return None


def get_cover_path(media_id: str) -> Path | None:
    """Return the local file path for a cover if it exists."""
    path = settings.covers_dir / f"{media_id}.jpg"
    return path if path.exists() else None


def _resized_path(media_id: str, size: int) -> Path:
    return settings.covers_dir / f"{media_id}_{size}.jpg"


def clear_resized(media_id: str) -> None:
    """Drop cached resized variants (call when the base cover changes)."""
    for p in settings.covers_dir.glob(f"{media_id}_*.jpg"):
        try:
            p.unlink()
        except OSError:
            pass


def get_or_make_resized(media_id: str, size: int) -> Path | None:
    """Return a cached NxN variant of the base cover, generating it on first request.

    Lets embedded clients (ESPHome) fetch covers already at the display size — no client-side
    scaling (sharper, less RAM/CPU on the device). Returns None if the base cover is missing.
    """
    base = get_cover_path(media_id)
    if base is None:
        return None
    variant = _resized_path(media_id, size)
    if variant.exists():
        return variant
    try:
        img = Image.open(base).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        img.save(variant, "JPEG", quality=85, optimize=True)
        return variant
    except Exception as exc:
        logger.warning("Failed to resize cover %s @ %dpx: %s", media_id, size, exc)
        return None


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


# --- Thumbnail proxy cache --------------------------------------------------------------
#
# Episode / now-playing artwork lives on the music provider's CDN (or behind the Music
# Assistant imageproxy). Embedded clients can't hit those directly without paying a slow TLS
# handshake to a third-party host on every image — enough to starve the device's main loop —
# and we'd rather not depend on a third-party resizer either. Instead we fetch each image
# once, resize it ourselves, cache the JPEG (keyed by a hash of the source URL + size), and
# let the device pull it from us (fast, plaintext-friendly, cached).
#
# The source URL can be any host, so we don't allow-list hosts; instead the proxy URL carries
# an HMAC signature (`sign_thumb`) and the endpoint refuses anything we didn't sign — closing
# the open-proxy / SSRF hole without a list to maintain.


def sign_thumb(src_url: str, size: int) -> str:
    """HMAC signature binding a source URL to a size (hex, truncated)."""
    msg = f"{src_url}|{size}".encode("utf-8")
    return hmac.new(_THUMB_KEY, msg, hashlib.sha256).hexdigest()[:16]


def verify_thumb(src_url: str, size: int, sig: str) -> bool:
    """Constant-time check that `sig` was produced by us for this (src, size)."""
    return hmac.compare_digest(sign_thumb(src_url, size), sig or "")


def thumb_proxy_url(base: str, src_url: str | None, size: int) -> str | None:
    """Build a signed `/api/v1/quick/thumb` URL for a source image (None if no source)."""
    if not src_url:
        return None
    sig = sign_thumb(src_url, size)
    return f"{base}/api/v1/quick/thumb?src={quote(src_url, safe='')}&size={size}&sig={sig}"


def _thumb_variant_path(src_url: str, size: int) -> Path:
    key = hashlib.sha256(src_url.encode("utf-8")).hexdigest()[:32]
    return settings.thumbs_dir / f"{key}_{size}.jpg"


def _enforce_thumb_cache_limit() -> None:
    """Evict the oldest thumbnails (LRU by mtime) when the cache exceeds its size cap.

    Runs only after a cache miss writes a new file. To avoid purging on every write once
    we sit near the limit, we trim down to a low-water mark (90% of the cap) in one pass.
    """
    max_bytes = settings.thumb_cache_max_bytes
    if max_bytes <= 0:
        return

    entries: list[tuple[float, int, Path]] = []
    total = 0
    for p in settings.thumbs_dir.glob("*.jpg"):
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
        total += st.st_size

    if total <= max_bytes:
        return

    target = int(max_bytes * 0.9)
    for _mtime, size, path in sorted(entries):  # oldest first
        if total <= target:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass
    logger.info("Thumbnail cache trimmed to %d bytes (cap %d)", total, max_bytes)


async def get_or_make_thumb(src_url: str, size: int) -> Path | None:
    """Fetch an external image once, cache an NxN JPEG variant, return its path.

    Returns the cached file on a hit; otherwise downloads `src_url`, resizes to a square
    `size`, caches it, and returns it. Returns None on download/decode failure (the caller
    falls back to the default cover). The caller is responsible for authorising `src_url`
    (the endpoint verifies an HMAC signature — see `verify_thumb`).
    """
    variant = _thumb_variant_path(src_url, size)
    if variant.exists():
        return variant

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(src_url, follow_redirects=True)
            resp.raise_for_status()
            raw_bytes = resp.content
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch thumbnail from %s: %s", src_url, exc)
        return None

    try:
        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
        img.save(variant, "JPEG", quality=85, optimize=True)
        _enforce_thumb_cache_limit()
        return variant
    except Exception as exc:
        logger.warning("Failed to process thumbnail from %s: %s", src_url, exc)
        return None


def delete_cover(media_id: str) -> None:
    """Delete the locally cached cover for a media item."""
    path = settings.covers_dir / f"{media_id}.jpg"
    if path.exists():
        path.unlink()
        logger.info("Deleted cover for media %s", media_id)
    clear_resized(media_id)
