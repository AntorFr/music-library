"""SQLAlchemy models for the media catalogue."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MediaType(str, enum.Enum):
    playlist = "playlist"
    audiobook = "audiobook"
    radio = "radio"
    podcast = "podcast"
    album = "album"
    track = "track"


# Default tag categories (used for seeding only — the source of truth is the DB)
DEFAULT_TAG_CATEGORIES: dict[str, str] = {
    "owner": "Propriétaire",
    "mood": "Humeur",
    "context": "Contexte",
    "genre": "Genre",
    "time_of_day": "Moment",
    "age_group": "Tranche d'âge",
}


# ---------------------------------------------------------------------------
# Association table
# ---------------------------------------------------------------------------

class MediaTag(Base):
    """Many-to-many link between Media and Tag."""

    __tablename__ = "media_tags"

    media_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

class Media(Base):
    __tablename__ = "media"

    __table_args__ = (
        UniqueConstraint("provider", "source_uri", name="uq_media_provider_source_uri"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), nullable=False, index=True)
    source_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Cover art
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cover_local: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Optional metadata
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    tags: Mapped[list[Tag]] = relationship(
        "Tag", secondary="media_tags", back_populates="media", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Media {self.id[:8]} '{self.title}' ({self.media_type.value})>"


# ---------------------------------------------------------------------------
# Tag Category (dynamic — managed via UI)
# ---------------------------------------------------------------------------

class TagCategoryModel(Base):
    """Dynamic tag categories stored in DB, manageable via the UI."""

    __tablename__ = "tag_categories"

    slug: Mapped[str] = mapped_column(String(50), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    tags: Mapped[list["Tag"]] = relationship("Tag", back_populates="category_rel", lazy="selectin")

    def __repr__(self) -> str:
        return f"<TagCategory {self.slug} ({self.label})>"


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------

class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(
        String(50), ForeignKey("tag_categories.slug", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    value: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("category", "value", name="uq_tag_category_value"),
        Index("ix_tag_category_value", "category", "value"),
    )

    # Relationships
    category_rel: Mapped[TagCategoryModel] = relationship("TagCategoryModel", back_populates="tags", lazy="selectin")
    media: Mapped[list[Media]] = relationship(
        "Media", secondary="media_tags", back_populates="tags", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Tag {self.category}:{self.value}>"

    @property
    def display(self) -> str:
        return f"{self.category}:{self.value}"
