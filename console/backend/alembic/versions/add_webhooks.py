"""Add webhooks table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_0008"
down_revision = "20260406_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("signing_secret", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhooks_project_id", "webhooks", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_webhooks_project_id", table_name="webhooks")
    op.drop_table("webhooks")
