"""Add secret-history archival and project retention policy."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0019"
down_revision = "20260808_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("secrets", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_secrets_archived_at", "secrets", ["archived_at"])
    op.add_column(
        "projects",
        sa.Column("secret_retention_versions", sa.Integer(), server_default="100", nullable=False),
    )
    op.add_column("projects", sa.Column("secret_retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "projects", sa.Column("secret_archive_deleted_after_days", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("projects", "secret_archive_deleted_after_days")
    op.drop_column("projects", "secret_retention_days")
    op.drop_column("projects", "secret_retention_versions")
    op.drop_index("ix_secrets_archived_at", table_name="secrets")
    op.drop_column("secrets", "archived_at")
