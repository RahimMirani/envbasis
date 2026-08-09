"""Record the provider used to wrap each project data-encryption key."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0011"
down_revision = "20260807_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_encryption_keys",
        sa.Column(
            "wrapping_provider",
            sa.String(length=32),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "project_encryption_keys",
        sa.Column("wrapping_key_id", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_encryption_keys", "wrapping_key_id")
    op.drop_column("project_encryption_keys", "wrapping_provider")
