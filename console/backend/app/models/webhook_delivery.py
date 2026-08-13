from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class WebhookDelivery(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index(
            "ix_webhook_deliveries_webhook_id_created_at",
            "webhook_id",
            "created_at",
        ),
        Index(
            "ix_webhook_deliveries_status_next_attempt_at",
            "status",
            "next_attempt_at",
        ),
        UniqueConstraint(
            "webhook_id",
            "idempotency_key",
            name="uq_webhook_deliveries_webhook_idempotency_key",
        ),
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[list["WebhookDeliveryAttempt"]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WebhookDeliveryAttempt.attempt_number",
    )
