"""Add durable encrypted API idempotency records."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0015"
down_revision = "20260807_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("encrypted_response_body", sa.LargeBinary(), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_hash",
            "method",
            "path",
            "idempotency_key",
            name="uq_api_idempotency_scope_key",
        ),
    )
    op.create_index(
        "ix_api_idempotency_records_expires_at",
        "api_idempotency_records",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_idempotency_records_expires_at",
        table_name="api_idempotency_records",
    )
    op.drop_table("api_idempotency_records")
