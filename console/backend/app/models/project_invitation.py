from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ProjectInvitation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Pending or historical project invitation by email."""

    __tablename__ = "project_invitations"
    __table_args__ = (
        UniqueConstraint("invite_token_hash", name="uq_project_invitations_token_hash"),
        Index("ix_project_invitations_project_id", "project_id"),
        Index("ix_project_invitations_email_normalized", "email_normalized"),
        Index("ix_project_invitations_status", "status"),
        Index(
            "uq_project_invitations_pending_project_email",
            "project_id",
            "email_normalized",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    can_push_pull_secrets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_manage_runtime_tokens: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_manage_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_audit_logs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    invite_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
