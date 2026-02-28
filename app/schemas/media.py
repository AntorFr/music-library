"""Pydantic schemas for Media and Tag resources."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field
from pydantic import field_validator

from app.models.media import MediaType


# ---------------------------------------------------------------------------
# Tag category schemas
# ---------------------------------------------------------------------------

class TagCategoryCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    label: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')


class TagCategoryRead(BaseModel):
    slug: str
    label: str
    color: str | None = None
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


class MediaSelectRead(MediaRead):
    """Selection result for HA: includes a stable resolved cover URL."""

    cover_url_resolved: str


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


class SelectionFallback(str, enum.Enum):
    """Fallback mode when strict selection returns 0 items."""

    none = "none"
    soft = "soft"
    aggressive = "aggressive"
    force = "force"


class TagFilter(BaseModel):
    """Tag filter for a single category.

    Semantics: values are OR within a category.
    """

    category: str = Field(..., min_length=1, max_length=50)
    values: list[str] = Field(default_factory=list)

    @field_validator("values", mode="before")
    @classmethod
    def _coerce_values(cls, v):
        # Accept either list[str] or CSV string.
        if v is None:
            return []
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            out: list[str] = []
            for item in v:
                if item is None:
                    continue
                if isinstance(item, str):
                    out.extend([p.strip() for p in item.split(",") if p.strip()])
                else:
                    out.append(str(item))
            return out
        return v


class TagQueryGroup(BaseModel):
    """Recursive boolean query over tags.

    - all_of: AND across categories
    - none_of: NOT (exclusion), exclusion is always strict
    - any_of: OR across nested groups
    """

    all_of: list[TagFilter] = Field(default_factory=list)
    any_of: list["TagQueryGroup"] = Field(default_factory=list)
    none_of: list[TagFilter] = Field(default_factory=list)


class MediaSelectQueryOptions(BaseModel):
    """Options for selection, used by HA integrations."""

    limit: int = Field(10, ge=1, le=100)
    random: bool = False
    fallback: SelectionFallback = SelectionFallback.none
    exclude_ids: list[str] = Field(default_factory=list, description="UUIDs à exclure")

    # Strict filters (never relaxed by fallback)
    media_type: MediaType | None = None
    provider: str | None = None
    search: str | None = Field(None, description="Filtre par nom (LIKE %search%)")

    @field_validator("exclude_ids", mode="before")
    @classmethod
    def _coerce_exclude_ids(cls, v):
        # Accept list[str] or CSV string.
        if v is None:
            return []
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v


class MediaSelectQueryRequest(BaseModel):
    """POST payload for complex selection queries."""

    query: TagQueryGroup
    options: MediaSelectQueryOptions = Field(default_factory=MediaSelectQueryOptions)


# Resolve recursive model references
TagQueryGroup.model_rebuild()


# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel):
    items: list[MediaRead]
    total: int
    page: int
    page_size: int
    pages: int
