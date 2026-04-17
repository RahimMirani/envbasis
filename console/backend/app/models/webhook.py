from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Webhook(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "webhooks"
    __table_args__ = (Index("ix_webhooks_project_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    signing_secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Per-instance plaintext cache so we decrypt at most once per loaded object,
    # and so we can hand back the plaintext we just set without a round-trip.
    _signing_secret_plaintext_cache: str | None = None

    def set_signing_secret(self, plaintext: str) -> None:
        # Local import avoids a circular import at module load time
        # (services.crypto imports settings which imports models indirectly).
        from app.services.crypto import encrypt_text

        self.signing_secret_ciphertext = encrypt_text(plaintext)
        self._signing_secret_plaintext_cache = plaintext

    @property
    def signing_secret(self) -> str:
        cached = self._signing_secret_plaintext_cache
        if cached is not None:
            return cached

        from app.services.crypto import decrypt_text

        plaintext = decrypt_text(self.signing_secret_ciphertext)
        self._signing_secret_plaintext_cache = plaintext
        return plaintext
