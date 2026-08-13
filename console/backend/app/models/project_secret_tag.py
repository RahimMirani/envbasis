from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ProjectSecretTag(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_secret_tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_secret_tags_project_name"),
        Index("ix_project_secret_tags_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
