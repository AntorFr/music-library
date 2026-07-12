"""Permission rules for the parent/child role model.

Parents (and machine callers) are unrestricted. A child is scoped to the media
carrying the owner tag matching their username — see ``services/auth_service``.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.services.auth_service import CurrentUser

#: Tag category that carries media ownership.
OWNER_CATEGORY = "owner"


def media_owner_values(item) -> set[str]:
    """Casefolded values of the owner tags carried by a media item."""
    return {
        t.value.casefold()
        for t in (getattr(item, "tags", []) or [])
        if t.category == OWNER_CATEGORY and t.value
    }


def can_access_media(user: CurrentUser, item) -> bool:
    """View/edit rule: a child only reaches media carrying their owner tag."""
    return user.owner_value is None or user.owner_value in media_owner_values(item)


def ensure_media_access(user: CurrentUser, item) -> None:
    """Raise 404 when the item is missing — or hidden from this user.

    Out-of-scope media answers 404 (not 403) so a child cannot probe the
    existence of other people's items.
    """
    if item is None or not can_access_media(user, item):
        raise HTTPException(404, detail="Média introuvable")


def ensure_parent(user: CurrentUser) -> None:
    """Gate for management surfaces (tags, RFID, bulk import…)."""
    if not user.is_parent:
        raise HTTPException(403, detail="Réservé aux parents")


def is_own_owner_tag(user: CurrentUser, tag) -> bool:
    """True when the tag is the child's own owner tag (which they cannot remove)."""
    return (
        user.owner_value is not None
        and tag.category == OWNER_CATEGORY
        and (tag.value or "").casefold() == user.owner_value
    )
