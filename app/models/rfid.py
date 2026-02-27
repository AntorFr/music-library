"""RFID tag model.

A RFID tag can be associated to at most one Media item.
A Media item can have multiple RFID tags.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RFIDTag(Base):
    __tablename__ = "rfid_tags"

    uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Nullable FK: unassigned tags are available for association.
    media_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media.id", ondelete="SET NULL"), nullable=True, index=True
    )

    media = relationship("Media", back_populates="rfid_tags", lazy="selectin")

    __table_args__ = (
        Index("ix_rfid_media_id", "media_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RFIDTag {self.uid} name={self.name!r} media_id={self.media_id}>"
