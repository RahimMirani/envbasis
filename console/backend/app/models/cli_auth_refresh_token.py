from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class CliAuthRefreshToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "cli_auth_refresh_tokens"
    __table_args__ = (
        Index("uq_cli_auth_refresh_tokens_token_hash", "token_hash", unique=True),
        Index("ix_cli_auth_refresh_tokens_user_id", "user_id"),
        Index("ix_cli_auth_refresh_tokens_session_id", "cli_auth_session_id"),
        Index("ix_cli_auth_refresh_tokens_expires_at", "expires_at"),
        Index("ix_cli_auth_refresh_tokens_revoked_at", "revoked_at"),
    )

    cli_auth_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cli_auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cli_auth_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
