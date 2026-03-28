from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class RuntimeToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "runtime_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_runtime_tokens_token_hash"),
        Index("ix_runtime_tokens_project_id", "project_id"),
        Index("ix_runtime_tokens_environment_id", "environment_id"),
        Index("ix_runtime_tokens_created_by", "created_by"),
        Index("ix_runtime_tokens_expires_at", "expires_at"),
        Index(
            "uq_runtime_tokens_active_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_token: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
