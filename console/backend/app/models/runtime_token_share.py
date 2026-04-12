from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class RuntimeTokenShare(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "runtime_token_shares"
    __table_args__ = (
        UniqueConstraint("runtime_token_id", "user_id", name="uq_runtime_token_shares_token_user"),
        Index("ix_runtime_token_shares_runtime_token_id", "runtime_token_id"),
        Index("ix_runtime_token_shares_user_id", "user_id"),
    )

    runtime_token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runtime_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    shared_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    can_manage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

