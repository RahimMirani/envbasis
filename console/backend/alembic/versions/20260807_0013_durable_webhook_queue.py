"""Turn webhook deliveries into durable retryable jobs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0013"
down_revision = "20260807_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_deliveries", sa.Column("payload", sa.Text(), nullable=True))
    op.add_column(
        "webhook_deliveries",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Historical rows are already complete and will never be claimed by the worker.
    op.execute("UPDATE webhook_deliveries SET payload = '{}' WHERE payload IS NULL")
    op.alter_column("webhook_deliveries", "payload", nullable=False)
    op.create_index(
        "ix_webhook_deliveries_status_next_attempt_at",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_status_next_attempt_at",
        table_name="webhook_deliveries",
    )
    op.drop_column("webhook_deliveries", "last_attempt_at")
    op.drop_column("webhook_deliveries", "next_attempt_at")
    op.drop_column("webhook_deliveries", "max_attempts")
    op.drop_column("webhook_deliveries", "attempt_count")
    op.drop_column("webhook_deliveries", "payload")
