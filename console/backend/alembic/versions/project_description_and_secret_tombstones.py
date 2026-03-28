"""Add project descriptions and secret tombstones."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260313_0004"
down_revision = "20260312_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("description", sa.String(length=1000), nullable=True))
    op.add_column(
        "secrets",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("secrets", "is_deleted")
    op.drop_column("projects", "description")
