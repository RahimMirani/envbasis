"""Add path and tag selectors to versioned secrets."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0016"
down_revision = "20260807_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "secrets",
        sa.Column("path", sa.String(length=512), server_default="/", nullable=False),
    )
    op.add_column(
        "secrets",
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.create_index("ix_secrets_environment_path", "secrets", ["environment_id", "path"])


def downgrade() -> None:
    op.drop_index("ix_secrets_environment_path", table_name="secrets")
    op.drop_column("secrets", "tags")
    op.drop_column("secrets", "path")
