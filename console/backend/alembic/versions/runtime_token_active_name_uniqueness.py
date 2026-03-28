"""Add unique active runtime token names per project."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260314_0005"
down_revision = "20260313_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_runtime_tokens_active_project_name",
        "runtime_tokens",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_runtime_tokens_active_project_name", table_name="runtime_tokens")
