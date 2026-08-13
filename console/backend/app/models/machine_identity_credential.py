from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class MachineIdentityCredential(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "machine_identity_credentials"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_machine_identity_credentials_client_id"),
        Index("ix_machine_identity_credentials_identity_id", "identity_id"),
        Index("ix_machine_identity_credentials_revoked_at", "revoked_at"),
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("machine_identities.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(64), nullable=False, default="universal-auth")
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overlap_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MachineIdentityAuthEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "machine_identity_auth_events"
    __table_args__ = (
        Index("ix_machine_identity_auth_events_identity_id", "identity_id"),
        Index("ix_machine_identity_auth_events_created_at", "created_at"),
    )

    identity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machine_identities.id", ondelete="CASCADE"), nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machine_identity_credentials.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
