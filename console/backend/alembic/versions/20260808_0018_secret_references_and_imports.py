"""Add reference markers and deterministic environment/folder imports."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0018"
down_revision = "20260808_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "secrets",
        sa.Column("is_reference", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "secret_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_environment_id", sa.Uuid(), nullable=False),
        sa.Column("target_path", sa.String(length=512), nullable=False),
        sa.Column("source_environment_id", sa.Uuid(), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("recursive", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_environment_id",
            "target_path",
            "source_environment_id",
            "source_path",
            name="uq_secret_imports_mapping",
        ),
    )
    op.create_index(
        "ix_secret_imports_target", "secret_imports", ["target_environment_id", "target_path"]
    )
    op.create_index(
        "ix_secret_imports_source", "secret_imports", ["source_environment_id", "source_path"]
    )


def downgrade() -> None:
    op.drop_index("ix_secret_imports_source", table_name="secret_imports")
    op.drop_index("ix_secret_imports_target", table_name="secret_imports")
    op.drop_table("secret_imports")
    op.drop_column("secrets", "is_reference")
