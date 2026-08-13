from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class MachineIdentity(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "machine_identities"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_machine_identities_client_id"),
        CheckConstraint(
            "(project_id IS NOT NULL AND organization_id IS NULL) OR "
            "(project_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_machine_identities_exactly_one_scope",
        ),
        Index("ix_machine_identities_project_id", "project_id"),
        Index("ix_machine_identities_organization_id", "organization_id"),
        Index("ix_machine_identities_environment_id", "environment_id"),
        Index("ix_machine_identities_created_by", "created_by"),
        Index("ix_machine_identities_revoked_at", "revoked_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    credential_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    access_token_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_secret_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    trusted_cidrs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_auth_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
