"""Add webhook idempotency keys and per-attempt history."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0014"
down_revision = "20260807_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_webhook_deliveries_webhook_idempotency_key",
        "webhook_deliveries",
        ["webhook_id", "idempotency_key"],
    )
    op.create_table(
        "webhook_delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["webhook_deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_id",
            "attempt_number",
            name="uq_webhook_delivery_attempt_number",
        ),
    )
    op.create_index(
        "ix_webhook_delivery_attempts_delivery_started_at",
        "webhook_delivery_attempts",
        ["delivery_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_delivery_attempts_delivery_started_at",
        table_name="webhook_delivery_attempts",
    )
    op.drop_table("webhook_delivery_attempts")
    op.drop_constraint(
        "uq_webhook_deliveries_webhook_idempotency_key",
        "webhook_deliveries",
        type_="unique",
    )
    op.drop_column("webhook_deliveries", "idempotency_key")
