"""Permission rules for the parent/child role model.

Parents (and machine callers) are unrestricted. A child is scoped to the media
carrying the owner tag matching their username — see ``services/auth_service``.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.services.auth_service import CurrentUser, normalize_owner

#: Tag category that carries media ownership.
OWNER_CATEGORY = "owner"


def media_owner_values(item) -> set[str]:
    """Normalised values of the owner tags carried by a media item."""
    return {
        normalize_owner(t.value)
        for t in (getattr(item, "tags", []) or [])
        if t.category == OWNER_CATEGORY and t.value
    }


def can_view_media(user: CurrentUser, item) -> bool:
    """View rule: a child sees media carrying their own tag or a group tag."""
    keys = user.view_owner_keys
    return keys is None or bool(keys & media_owner_values(item))


def can_edit_media(user: CurrentUser, item) -> bool:
    """Edit rule: a child only modifies media carrying their OWN owner tag.

    Group-shared media (``owner:famille``…) stay visible but read-only for them.
    """
    return user.owner_value is None or user.owner_value in media_owner_values(item)


def ensure_media_access(user: CurrentUser, item) -> None:
    """Raise 404 when the item is missing — or hidden from this user.

    Out-of-scope media answers 404 (not 403) so a child cannot probe the
    existence of other people's items.
    """
    if item is None or not can_view_media(user, item):
        raise HTTPException(404, detail="Média introuvable")


def ensure_media_edit(user: CurrentUser, item) -> None:
    """404 when invisible, 403 when visible but not theirs to modify."""
    ensure_media_access(user, item)
    if not can_edit_media(user, item):
        raise HTTPException(403, detail="Média partagé — modification réservée aux parents")


def ensure_parent(user: CurrentUser) -> None:
    """Gate for management surfaces (tags, RFID, bulk import…)."""
    if not user.is_parent:
        raise HTTPException(403, detail="Réservé aux parents")


def is_own_owner_tag(user: CurrentUser, tag) -> bool:
    """True when the tag is the child's own owner tag (which they cannot remove)."""
    return (
        user.owner_value is not None
        and tag.category == OWNER_CATEGORY
        and normalize_owner(tag.value or "") == user.owner_value
    )
