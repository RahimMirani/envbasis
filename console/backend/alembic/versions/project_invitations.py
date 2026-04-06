"""Add project_invitations for pending invite lifecycle."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260406_0007"
down_revision = "20260318_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("can_push_pull_secrets", sa.Boolean(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("invite_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_token_hash", name="uq_project_invitations_token_hash"),
    )
    op.create_index("ix_project_invitations_project_id", "project_invitations", ["project_id"], unique=False)
    op.create_index(
        "ix_project_invitations_email_normalized",
        "project_invitations",
        ["email_normalized"],
        unique=False,
    )
    op.create_index("ix_project_invitations_status", "project_invitations", ["status"], unique=False)
    op.create_index(
        "uq_project_invitations_pending_project_email",
        "project_invitations",
        ["project_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_invitations_pending_project_email", table_name="project_invitations")
    op.drop_index("ix_project_invitations_status", table_name="project_invitations")
    op.drop_index("ix_project_invitations_email_normalized", table_name="project_invitations")
    op.drop_index("ix_project_invitations_project_id", table_name="project_invitations")
    op.drop_table("project_invitations")
