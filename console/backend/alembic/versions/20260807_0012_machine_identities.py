"""Add scoped machine identities with hash-only client credentials."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0012"
down_revision = "20260807_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_token_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("allowed_actions", sa.JSON(), nullable=False),
        sa.Column("allowed_secret_keys", sa.JSON(), nullable=True),
        sa.Column("trusted_cidrs", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_machine_identities_client_id"),
    )
    op.create_index("ix_machine_identities_project_id", "machine_identities", ["project_id"])
    op.create_index("ix_machine_identities_environment_id", "machine_identities", ["environment_id"])
    op.create_index("ix_machine_identities_created_by", "machine_identities", ["created_by"])
    op.create_index("ix_machine_identities_revoked_at", "machine_identities", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_machine_identities_revoked_at", table_name="machine_identities")
    op.drop_index("ix_machine_identities_created_by", table_name="machine_identities")
    op.drop_index("ix_machine_identities_environment_id", table_name="machine_identities")
    op.drop_index("ix_machine_identities_project_id", table_name="machine_identities")
    op.drop_table("machine_identities")
