"""Pin a local media row to one Spotify account (MA provider instance).

A ``library://`` URI lets Music Assistant pick the account itself, and it does so
without checking that the account still works: it takes the "first" provider mapping
of an unordered set, disabled instances included. A podcast then lists 0 episodes
the day that pick lands on a dead account (see docs/MUSIC_ASSISTANT_COMPATIBILITY.md).

An instance URI (``spotify--ThNy9kHW://podcast/<id>``) is what the web page and the
dashboard API address directly, so rewriting ``source_uri`` to one pins the account.
Spotify ids are global, so the same id is valid under every account that can see it;
a private playlist may still be invisible to another account, hence the probe before
writing anything.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media, MediaType
from app.schemas.media import MediaUpdate
from app.services import media_service

SPOTIFY_DOMAIN = "spotify"

#: Media whose content is a list fetched through the account — the only ones where
#: the account decides between "works" and "0 items".
SWITCHABLE_TYPES = frozenset({MediaType.podcast, MediaType.playlist, MediaType.album})


class AccountSwitchError(RuntimeError):
    """The switch was refused; the message is shown as is to the parent."""


def _split_uri(uri: str) -> tuple[str, str, str] | None:
    """``scheme://media_type/item_id`` → its three parts, or None if unparseable."""
    if "://" not in uri:
        return None
    scheme, rest = uri.split("://", 1)
    media_type, _, item_id = rest.partition("/")
    if not media_type or not item_id:
        return None
    return scheme, media_type, item_id


def _is_spotify_scheme(scheme: str) -> bool:
    return scheme == SPOTIFY_DOMAIN or scheme.startswith(f"{SPOTIFY_DOMAIN}--")


def is_switchable(item: Media) -> bool:
    """True for a Spotify-backed list (podcast, playlist, album) addressed through MA."""
    if item.media_type not in SWITCHABLE_TYPES:
        return False
    if (item.provider or "").split("--")[0] != SPOTIFY_DOMAIN:
        return False
    parts = _split_uri(item.source_uri or "")
    return parts is not None and (parts[0] == "library" or _is_spotify_scheme(parts[0]))


def current_account(item: Media) -> str | None:
    """Instance id the row is pinned to, or None when MA picks (``library://``)."""
    parts = _split_uri(item.source_uri or "")
    if parts and parts[0].startswith(f"{SPOTIFY_DOMAIN}--"):
        return parts[0]
    return None


async def list_accounts(ma: Any) -> list[dict]:
    """Spotify accounts configured in MA, usable ones first.

    ``usable`` means loaded: a disabled instance, or one whose login failed, is
    listed so the parent sees why it is greyed out, but cannot be picked.
    """
    configs = await ma.get_provider_configs()
    accounts = []
    for c in configs or []:
        if c.get("domain") != SPOTIFY_DOMAIN:
            continue
        error = c.get("last_error")
        if isinstance(error, dict):
            error = error.get("message")
        accounts.append({
            "instance_id": c.get("instance_id"),
            "name": c.get("name") or c.get("default_name") or c.get("instance_id"),
            "usable": c.get("status") == "loaded",
            "error": error or (None if c.get("enabled") else "désactivé"),
        })
    accounts.sort(key=lambda a: (not a["usable"], str(a["name"]).casefold()))
    return accounts


async def spotify_item_id(ma: Any, item: Media) -> str:
    """The Spotify id behind the row, whatever account (or library) it goes through."""
    parts = _split_uri(item.source_uri or "")
    if parts is None:
        raise AccountSwitchError("Adresse du média illisible")
    scheme, media_type, item_id = parts
    if _is_spotify_scheme(scheme):
        return item_id
    library_item = await ma.get_item(media_type, item_id, "library")
    for mapping in library_item.provider_mappings:
        if mapping.get("provider_domain") == SPOTIFY_DOMAIN and mapping.get("item_id"):
            return str(mapping["item_id"])
    raise AccountSwitchError("Ce média n'a pas d'équivalent Spotify dans Music Assistant")


async def count_items(ma: Any, media_type: MediaType, item_id: str, instance_id: str) -> int:
    """How many episodes / tracks the account returns — 0 is what a dead pick looks like."""
    if media_type == MediaType.podcast:
        return len(await ma.get_podcast_episodes(item_id, instance_id))
    if media_type == MediaType.playlist:
        return len(await ma.get_playlist_tracks(item_id, instance_id))
    return len(await ma.get_album_tracks(item_id, instance_id))


async def switch_account(db: AsyncSession, ma: Any, item: Media, instance_id: str) -> Media:
    """Rewrite ``source_uri`` so the row goes through ``instance_id``.

    Nothing is written unless that account actually returns content for the item.
    """
    if not is_switchable(item):
        raise AccountSwitchError("Ce média ne passe pas par un compte Spotify")
    accounts = {a["instance_id"]: a for a in await list_accounts(ma)}
    account = accounts.get(instance_id)
    if account is None:
        raise AccountSwitchError("Compte Spotify inconnu de Music Assistant")
    if not account["usable"]:
        raise AccountSwitchError(f"{account['name']} ne fonctionne pas : {account['error']}")

    sid = await spotify_item_id(ma, item)
    if await count_items(ma, item.media_type, sid, instance_id) == 0:
        raise AccountSwitchError(
            f"{account['name']} ne renvoie rien pour ce média (privé sur un autre compte ?)"
        )

    extra = dict(item.metadata_extra or {})
    extra["ma_item_id"] = sid
    new_uri = f"{instance_id}://{item.media_type.value}/{sid}"
    try:
        updated = await media_service.update_media(
            db, item.id, MediaUpdate(source_uri=new_uri, metadata_extra=extra)
        )
    except media_service.DuplicateMediaError as exc:
        raise AccountSwitchError(
            "Ce média existe déjà dans le catalogue sur ce compte"
        ) from exc
    return updated
