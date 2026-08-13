from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ProjectEncryptionKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "project_encryption_keys"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "version",
            name="uq_project_encryption_keys_project_version",
        ),
        Index("ix_project_encryption_keys_project_id", "project_id"),
        Index(
            "uq_project_encryption_keys_active_project",
            "project_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapping_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="local",
    )
    wrapping_key_id: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
