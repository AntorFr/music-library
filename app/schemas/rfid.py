"""Pydantic schemas for RFID tags."""

from __future__ import annotations

from pydantic import BaseModel, Field


RFID_UID_PATTERN = r"^[0-9A-Fa-f]{2}(-[0-9A-Fa-f]{2}){3,}$"


class RFIDTagUpsert(BaseModel):
    """Payload to create or rename a RFID tag (no association)."""

    name: str = Field(..., min_length=1, max_length=120)


class RFIDTagRead(BaseModel):
    uid: str = Field(..., pattern=RFID_UID_PATTERN, max_length=64)
    name: str
    media_id: str | None = None
    media_title: str | None = None


class RFIDResolveResponse(BaseModel):
    """Resolve a media title for a given RFID UID."""

    uid: str = Field(..., pattern=RFID_UID_PATTERN, max_length=64)
    media_id: str
    title: str
    source_uri: str
    provider: str
    cover_url_resolved: str
