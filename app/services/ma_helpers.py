"""Pure helpers around Music Assistant items (addressing, chapters, episode fetches).

Re-exported by :mod:`app.services.music_assistant`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.services.ma_models import MAMediaItem

if TYPE_CHECKING:
    from app.services.music_assistant import MusicAssistantClient


def resolve_ma_provider_and_id(item: Any) -> tuple[str | None, str | None]:
    """(provider, item_id) to re-query Music Assistant about a local media row.

    Prefer the ``source_uri``: it is the canonical MA URI (e.g. ``library://audiobook/29``),
    so its scheme is the MA provider and the trailing segment is the item id — a
    self-consistent pair. The stored ``provider`` column can be the *origin* provider
    (audible/spotify) while ``ma_item_id`` is the *library* id; combining those two is wrong
    and makes MA look up a non-existent item (``shows/88 not found``, ``ASIN 29 not present``).
    Fall back to provider + ma_item_id only when the source_uri can't be parsed.

    ``item`` is duck-typed: anything exposing ``source_uri``, ``provider`` and
    ``metadata_extra`` (a :class:`~app.models.media.Media` row, in practice).
    """
    uri = getattr(item, "source_uri", "") or ""
    if "://" in uri:
        scheme, rest = uri.split("://", 1)
        parts = rest.split("/", 1)
        if len(parts) == 2 and parts[1]:
            return scheme, parts[1]
    provider = (getattr(item, "provider", "") or "").strip() or None
    extra = getattr(item, "metadata_extra", None) or {}
    item_id = (
        str(extra["ma_item_id"])
        if isinstance(extra, dict) and extra.get("ma_item_id")
        else None
    )
    return provider, item_id


# Episode fetches currently running, keyed by (provider, item_id). A provider-backed podcast
# (e.g. Spotify) can take tens of seconds on a cold MA cache; clients that give up and retry
# must not stack identical MA commands on top of the one still running.
_episode_fetches: dict[tuple[str, str], asyncio.Task[list[MAMediaItem]]] = {}


async def _single_flight_episodes(
    ma: MusicAssistantClient, provider: str, item_id: str
) -> list[MAMediaItem]:
    """Join the running fetch for this podcast, or start one.

    This is request coalescing, not a cache: the entry is dropped as soon as MA answers, so
    the next request re-asks MA (resume positions stay fresh). The fetch runs in its own
    task and callers await it through ``shield``: a caller that disconnects does not cancel
    the fetch the other callers are waiting on.
    """
    key = (provider, item_id)
    task = _episode_fetches.get(key)
    if task is None:
        task = asyncio.create_task(ma.get_podcast_episodes(item_id, provider))
        _episode_fetches[key] = task
        task.add_done_callback(lambda t: _episode_fetches.pop(key, None))
    episodes = await asyncio.shield(task)
    return list(episodes)  # each caller gets its own list


async def fetch_podcast_episodes(
    ma: MusicAssistantClient, item: Any
) -> list[MAMediaItem]:
    """Episodes of a local podcast row, in MA's own objects.

    Callers serialise them their own way (HTMX template vs embedded-client JSON); what
    they must NOT own is *how the item is addressed* — see
    :func:`resolve_ma_provider_and_id`. Concurrent requests for the same podcast share one
    MA command (see :func:`_single_flight_episodes`).
    """
    provider, item_id = resolve_ma_provider_and_id(item)
    if not provider or not item_id:
        ma_item = await ma.get_item_by_uri(getattr(item, "source_uri", "") or "")
        provider, item_id = ma_item.provider, ma_item.item_id
    return await _single_flight_episodes(ma, provider, item_id)


async def fetch_audiobook(ma: MusicAssistantClient, item: Any) -> MAMediaItem:
    """The MA audiobook behind a local row — carries chapters, resume position, duration."""
    provider, item_id = resolve_ma_provider_and_id(item)
    if provider and item_id:
        return await ma.get_item("audiobook", item_id, provider)
    return await ma.get_item_by_uri(getattr(item, "source_uri", "") or "")


def normalize_chapters(ma_item: MAMediaItem) -> list[dict]:
    """Chapters as plain dicts, sorted by position, with ``end``/``duration`` in seconds.

    MA hands chapters over as raw dicts with stringy numbers; both surfaces need the same
    arithmetic, so it happens once here.
    """
    chapters = []
    for ch in ma_item.chapters:
        start = float(ch.get("start", 0) or 0)
        end = ch.get("end")
        end_f = float(end) if end is not None else None
        chapters.append({
            "position": int(ch.get("position", 0) or 0),
            "name": ch.get("name", "") or "",
            "start": start,
            "end": end_f,
            "duration": (end_f - start) if end_f else None,
        })
    chapters.sort(key=lambda c: c["position"])
    return chapters
