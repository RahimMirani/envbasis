"""Add per-project envelope-encryption keys and secret key versions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0010"
down_revision = "20260412_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_encryption_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_project_encryption_keys_project_version",
        ),
    )
    op.create_index(
        "ix_project_encryption_keys_project_id",
        "project_encryption_keys",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "uq_project_encryption_keys_active_project",
        "project_encryption_keys",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.add_column(
        "secrets",
        sa.Column("encryption_key_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration cannot be downgraded safely while secrets use project keys. "
        "Re-encrypt all secrets with the legacy root key before removing key metadata."
    )
