"""
Frontend (HTML) view routes.

Renders Jinja2 templates for the Music Library web UI.
All JSON API calls are delegated to the existing /api/v1/ routes.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

#: Cookie carrying the launcher profile. Written by the page, read here so the
#: very first response renders the right state (see ``listen_page``).
OWNER_COOKIE = "ml_owner"

router = APIRouter(tags=["frontend"])
templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# Shared template context helpers
# ---------------------------------------------------------------------------

TYPE_LABELS: dict[str, str] = {
    "playlist": "Playlist",
    "audiobook": "Livre audio",
    "radio": "Radio",
    "podcast": "Podcast",
    "album": "Album",
    "track": "Piste",
}

TYPE_ICONS: dict[str, str] = {
    "playlist": "playlist-music",
    "audiobook": "book-music",
    "radio": "radio",
    "podcast": "podcast",
    "album": "album",
    "track": "music-note",
}

TAG_COLOR_CHOICES: list[tuple[str, str, str]] = [
    ("red", "Rouge", "#f44336"),
    ("pink", "Rose", "#e91e63"),
    ("purple", "Violet", "#9c27b0"),
    ("deep-purple", "Violet foncé", "#673ab7"),
    ("indigo", "Indigo", "#3f51b5"),
    ("blue", "Bleu", "#2196f3"),
    ("light-blue", "Bleu clair", "#03a9f4"),
    ("cyan", "Cyan", "#00bcd4"),
    ("teal", "Turquoise", "#009688"),
    ("green", "Vert", "#4caf50"),
    ("light-green", "Vert clair", "#8bc34a"),
    ("lime", "Citron vert", "#cddc39"),
    ("yellow", "Jaune", "#ffeb3b"),
    ("amber", "Ambre", "#ffc107"),
    ("orange", "Orange", "#ff9800"),
    ("deep-orange", "Orange foncé", "#ff5722"),
    ("brown", "Marron", "#795548"),
    ("grey", "Gris", "#9e9e9e"),
    ("blue-grey", "Bleu gris", "#607d8b"),
]
TAG_COLOR_ALLOWED = {hex_color for _key, _label, hex_color in TAG_COLOR_CHOICES}

#: Display badge (label, mdi icon, CSS class) per MA provider domain.
PROVIDER_BADGES: dict[str, tuple[str, str, str]] = {
    "library": ("Bibliothèque", "mdi-bookshelf", "badge-success"),
    "spotify": ("Spotify", "mdi-spotify", "badge-primary"),
    "ytmusic": ("YouTube Music", "mdi-youtube", "badge-danger"),
    "apple_music": ("Apple Music", "mdi-apple", "badge-surface"),
    "tidal": ("Tidal", "mdi-music-box", "badge-primary"),
    "audible": ("Audible", "mdi-headphones", "badge-warning"),
}


def _provider_info(provider: str) -> dict:
    """Badge fields for a MA provider — instance ids ("spotify--ThNy9kHW") map to their domain."""
    base = provider.split("--")[0]
    label, icon, cls = PROVIDER_BADGES.get(base, (base.capitalize(), "mdi-cloud", "badge-surface"))
    return {
        "provider_label": label,
        "provider_icon": icon,
        "provider_badge": cls,
        "is_library": provider == "library",
    }


def _filter_url_builder(active: dict[str, str]):
    """Return a ``filter_url(**changes)`` the catalogue template calls per chip.

    Chips are links, not form controls: each one carries the URL the catalogue
    would have with that single filter flipped. No hidden inputs to keep in sync,
    no JS — and every filter state stays a bookmarkable address.
    Passing ``""`` (or None) for a key drops it.
    """
    def filter_url(**changes: str | None) -> str:
        params = {k: v for k, v in active.items() if v}
        for key, value in changes.items():
            if value:
                params[key] = value
            else:
                params.pop(key, None)
        params.pop("page", None)  # any filter change lands back on page 1
        query = urlencode(params)
        return f"/media?{query}" if query else "/media"
    return filter_url


async def _ma_status() -> dict:
    """Best-effort health of the Music Assistant link, for the Système tab.

    Reports the provider instances MA holds but cannot load: one of those silently
    returns an empty episode list instead of failing (see docs/MUSIC_ASSISTANT_COMPATIBILITY.md).
    """
    status: dict[str, Any] = {
        "reachable": False,
        "auth_failed": False,
        "error": None,
        "players": 0,
        "broken_providers": [],
    }
    try:
        from app.services.music_assistant import get_ma_client
        ma = await get_ma_client()
        status["players"] = len(await ma.get_players())
        status["reachable"] = True
        try:
            configs = await ma.get_provider_configs()
            status["broken_providers"] = [
                {"name": c.get("name") or c.get("instance_id"), "error": c.get("last_error")}
                for c in (configs or [])
                if c.get("enabled") and c.get("last_error")
            ]
        except Exception as exc:
            logger.info("MA provider configs unavailable: %s", exc)
    except Exception as exc:
        # A wrong token reaches MA and is refused — reporting that as "unreachable"
        # sends whoever reads this page debugging the network instead of the token.
        status["error"] = str(exc)
        status["auth_failed"] = "authentication" in str(exc).lower()
        logger.info("Music Assistant unavailable: %s", exc)
    return status


def _base_ctx(request: Request, **extra: Any) -> dict:
    """Build base template context."""
    return {
        "request": request,
        "type_labels": TYPE_LABELS,
        "type_icons": TYPE_ICONS,
        "current_user": get_current_user(request),
        **extra,
    }


def _build_available_tag_options(
    *,
    item: Any,
    all_tags: list[Any],
    cat_labels: dict[str, str],
) -> list[str]:
    existing = {(t.category, t.value) for t in (getattr(item, "tags", []) or [])}
    options: list[str] = []
    for t in all_tags:
        if (t.category, t.value) in existing:
            continue
        cat_label = cat_labels.get(t.category, t.category)
        options.append(f"{cat_label}: {t.value}")
    return sorted(set(options), key=str.casefold)


def _parse_tag_input(
    *,
    raw: str,
    cat_labels: dict[str, str],
) -> tuple[str, str]:
    """Parse a single tag input like '<Category>: <value>'.

    Accepts either a category slug or its label (case-insensitive).
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(400, detail="Tag invalide")

    if ":" not in raw:
        raise HTTPException(400, detail="Format attendu: 'Catégorie: valeur'")

    left, right = raw.split(":", 1)
    cat_token = left.strip()
    value = right.strip()
    if not cat_token or not value:
        raise HTTPException(400, detail="Format attendu: 'Catégorie: valeur'")

    label_to_slug = {lbl.casefold(): slug for slug, lbl in cat_labels.items()}
    slug = label_to_slug.get(cat_token.casefold(), cat_token)
    return slug, value

