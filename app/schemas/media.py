"""Pydantic schemas for Media and Tag resources."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.media import MediaType


# ---------------------------------------------------------------------------
# Tag category schemas
# ---------------------------------------------------------------------------

class TagCategoryCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    label: str = Field(..., min_length=1, max_length=100)


class TagCategoryRead(BaseModel):
    slug: str
    label: str
    tag_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Tag schemas
# ---------------------------------------------------------------------------

class TagBase(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    value: str = Field(..., min_length=1, max_length=100)


class TagCreate(TagBase):
    pass


class TagRead(TagBase):
    id: int
    display: str
    category_label: str = ""

    model_config = {"from_attributes": True}


class TagBrief(BaseModel):
    """Lightweight tag representation for embedding in media responses."""
    category: str
    value: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Media schemas
# ---------------------------------------------------------------------------

class MediaBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    media_type: MediaType
    source_uri: str = Field(..., min_length=1, max_length=512)
    provider: str = Field(..., min_length=1, max_length=50)
    cover_url: str | None = Field(None, max_length=1024)
    duration_min: int | None = Field(None, ge=0)
    description: str | None = None
    metadata_extra: dict | None = None


class MediaCreate(MediaBase):
    """Schema for creating a new media item. Tags are attached by id or by category:value."""
    tag_ids: list[int] = Field(default_factory=list)
    tags_inline: list[TagBase] = Field(
        default_factory=list,
        description="Tags to create-or-attach by category:value",
    )


class MediaUpdate(BaseModel):
    """Partial update — only provided fields are changed."""
    title: str | None = Field(None, min_length=1, max_length=255)
    media_type: MediaType | None = None
    source_uri: str | None = Field(None, min_length=1, max_length=512)
    provider: str | None = Field(None, min_length=1, max_length=50)
    cover_url: str | None = Field(None, max_length=1024)
    duration_min: int | None = Field(None, ge=0)
    description: str | None = None
    metadata_extra: dict | None = None
    is_active: bool | None = None
    tag_ids: list[int] | None = None
    tags_inline: list[TagBase] | None = None


class MediaRead(MediaBase):
    id: str
    cover_local: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    tags: list[TagBrief] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class MediaBrief(BaseModel):
    """Compact representation for lists / selection results."""
    id: str
    title: str
    media_type: MediaType
    source_uri: str
    provider: str
    cover_local: str | None = None
    tags: list[TagBrief] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Selection / query helpers
# ---------------------------------------------------------------------------

class MediaSelectParams(BaseModel):
    """Query parameters for the intelligent selection endpoint."""
    owner: str | None = None
    mood: str | None = None
    context: str | None = None
    genre: str | None = None
    time_of_day: str | None = None
    age_group: str | None = None
    media_type: MediaType | None = None
    provider: str | None = None
    random: bool = False
    limit: int = Field(10, ge=1, le=100)


# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel):
    items: list[MediaRead]
    total: int
    page: int
    page_size: int
    pages: int
