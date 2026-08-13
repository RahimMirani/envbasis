from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Secret(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "secrets"
    __table_args__ = (
        UniqueConstraint(
            "environment_id",
            "path",
            "key",
            "version",
            name="uq_secrets_env_path_key_version",
        ),
        Index("ix_secrets_environment_id", "environment_id"),
        Index("ix_secrets_environment_path", "environment_id", "path"),
        Index("ix_secrets_updated_by", "updated_by"),
        Index("ix_secrets_archived_at", "archived_at"),
    )

    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(320), nullable=True)
    service: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rotation_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_metadata: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    is_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
