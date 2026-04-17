"""Encrypt webhook signing secrets at rest.

Converts the plaintext `webhooks.signing_secret` column into an
encrypted `webhooks.signing_secret_ciphertext` (LargeBinary) column,
backfilling existing rows with Fernet ciphertext derived from
SECRETS_MASTER_KEY, and then drops the plaintext column.

Requires SECRETS_MASTER_KEY to be set in the environment when the
migration runs — the same key used for encrypting project secrets.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from cryptography.fernet import Fernet

from app.core.config import settings


revision = "20260416_0010"
down_revision = "20260410_0009"
branch_labels = None
depends_on = None


def _build_fernet() -> Fernet:
    key = settings.secrets_master_key
    if not key:
        raise RuntimeError(
            "SECRETS_MASTER_KEY must be set to run this migration: it "
            "re-encrypts existing webhook signing secrets in place."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "SECRETS_MASTER_KEY is not a valid Fernet key; cannot run "
            "the webhook signing-secret encryption migration."
        ) from exc


def upgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column("signing_secret_ciphertext", sa.LargeBinary(), nullable=True),
    )

    fernet = _build_fernet()
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, signing_secret FROM webhooks")).fetchall()
    for row in rows:
        plaintext = row.signing_secret
        if plaintext is None:
            continue
        ciphertext = fernet.encrypt(plaintext.encode("utf-8"))
        bind.execute(
            sa.text(
                "UPDATE webhooks SET signing_secret_ciphertext = :ciphertext "
                "WHERE id = :id"
            ),
            {"ciphertext": ciphertext, "id": row.id},
        )

    op.alter_column("webhooks", "signing_secret_ciphertext", nullable=False)
    op.drop_column("webhooks", "signing_secret")


def downgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column("signing_secret", sa.String(length=64), nullable=True),
    )

    fernet = _build_fernet()
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, signing_secret_ciphertext FROM webhooks")
    ).fetchall()
    for row in rows:
        ciphertext = row.signing_secret_ciphertext
        if ciphertext is None:
            continue
        plaintext = fernet.decrypt(ciphertext).decode("utf-8")
        bind.execute(
            sa.text("UPDATE webhooks SET signing_secret = :plaintext WHERE id = :id"),
            {"plaintext": plaintext, "id": row.id},
        )

    op.alter_column("webhooks", "signing_secret", nullable=False)
    op.drop_column("webhooks", "signing_secret_ciphertext")
