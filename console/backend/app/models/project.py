from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, NamedMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, CreatedAtMixin, NamedMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_owner_id", "owner_id"),
        Index("ix_projects_organization_id", "organization_id"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    audit_log_visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="owner_only",
    )
    secret_retention_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    secret_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    secret_archive_deleted_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
