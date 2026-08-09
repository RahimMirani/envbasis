"""Add hierarchical folders, project tags, and secret metadata."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260808_0017"
down_revision = "20260808_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("secrets", sa.Column("description", sa.String(length=1000), nullable=True))
    op.add_column("secrets", sa.Column("owner", sa.String(length=320), nullable=True))
    op.add_column("secrets", sa.Column("service", sa.String(length=128), nullable=True))
    op.add_column("secrets", sa.Column("rotation_interval_days", sa.Integer(), nullable=True))
    op.add_column("secrets", sa.Column("rotate_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "secrets",
        sa.Column("custom_metadata", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.drop_constraint("uq_secrets_env_key_version", "secrets", type_="unique")
    op.create_unique_constraint(
        "uq_secrets_env_path_key_version",
        "secrets",
        ["environment_id", "path", "key", "version"],
    )

    op.create_table(
        "secret_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("parent_path", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "path", name="uq_secret_folders_environment_path"),
    )
    op.create_index(
        "ix_secret_folders_environment_parent",
        "secret_folders",
        ["environment_id", "parent_path"],
    )

    op.create_table(
        "project_secret_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_secret_tags_project_name"),
    )
    op.create_index("ix_project_secret_tags_project_id", "project_secret_tags", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_secret_tags_project_id", table_name="project_secret_tags")
    op.drop_table("project_secret_tags")
    op.drop_index("ix_secret_folders_environment_parent", table_name="secret_folders")
    op.drop_table("secret_folders")
    op.drop_constraint("uq_secrets_env_path_key_version", "secrets", type_="unique")
    op.create_unique_constraint(
        "uq_secrets_env_key_version", "secrets", ["environment_id", "key", "version"]
    )
    op.drop_column("secrets", "custom_metadata")
    op.drop_column("secrets", "rotate_at")
    op.drop_column("secrets", "rotation_interval_days")
    op.drop_column("secrets", "service")
    op.drop_column("secrets", "owner")
    op.drop_column("secrets", "description")
