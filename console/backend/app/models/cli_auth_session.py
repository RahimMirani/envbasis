from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

CLI_AUTH_STATUS_PENDING = "pending"
CLI_AUTH_STATUS_APPROVED = "approved"
CLI_AUTH_STATUS_DENIED = "denied"
CLI_AUTH_STATUS_EXPIRED = "expired"
CLI_AUTH_STATUS_CONSUMED = "consumed"
CLI_AUTH_STATUSES = (
    CLI_AUTH_STATUS_PENDING,
    CLI_AUTH_STATUS_APPROVED,
    CLI_AUTH_STATUS_DENIED,
    CLI_AUTH_STATUS_EXPIRED,
    CLI_AUTH_STATUS_CONSUMED,
)


class CliAuthSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cli_auth_sessions"
    __table_args__ = (
        Index("uq_cli_auth_sessions_device_code_hash", "device_code_hash", unique=True),
        Index("uq_cli_auth_sessions_user_code_normalized", "user_code_normalized", unique=True),
        Index("ix_cli_auth_sessions_status", "status"),
        Index("ix_cli_auth_sessions_expires_at", "expires_at"),
        Index("ix_cli_auth_sessions_approved_by_user_id", "approved_by_user_id"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied', 'expired', 'consumed')",
            name="ck_cli_auth_sessions_status_valid",
        ),
    )

    device_code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    user_code: Mapped[str] = mapped_column(String(32), nullable=False)
    user_code_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CLI_AUTH_STATUS_PENDING)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    denied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
