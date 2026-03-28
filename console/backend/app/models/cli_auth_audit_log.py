from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class CliAuthAuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "cli_auth_audit_logs"
    __table_args__ = (
        Index("ix_cli_auth_audit_logs_cli_auth_session_id", "cli_auth_session_id"),
        Index("ix_cli_auth_audit_logs_user_id", "user_id"),
        Index("ix_cli_auth_audit_logs_action", "action"),
        Index("ix_cli_auth_audit_logs_created_at", "created_at"),
    )

    cli_auth_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cli_auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
