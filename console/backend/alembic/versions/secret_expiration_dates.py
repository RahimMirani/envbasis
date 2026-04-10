"""Add secret expiration dates."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_0009"
down_revision = "20260408_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "secrets",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("secrets", "expires_at")
