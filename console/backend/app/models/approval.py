from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ApprovalPolicy(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_policies"
    __table_args__ = (
        Index("ix_approval_policies_project_id", "project_id"),
        Index("ix_approval_policies_environment_id", "environment_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False, default="/")
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    steps: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    prevent_self_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_project_id", "project_id"),
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_author_id", "author_id"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_policies.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret_key: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    encrypted_value: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    secret_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequestEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_request_events"
    __table_args__ = (Index("ix_approval_request_events_request_id", "request_id"),)

    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
