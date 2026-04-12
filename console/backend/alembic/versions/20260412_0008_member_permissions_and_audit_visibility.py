"""Add member management permissions and project audit visibility."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_0008"
down_revision = "20260406_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "audit_log_visibility",
            sa.String(length=32),
            nullable=False,
            server_default="owner_only",
        ),
    )
    op.add_column(
        "project_members",
        sa.Column(
            "can_manage_runtime_tokens",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "project_members",
        sa.Column(
            "can_manage_team",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "project_invitations",
        sa.Column(
            "can_manage_runtime_tokens",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "project_invitations",
        sa.Column(
            "can_manage_team",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("project_invitations", "can_manage_team")
    op.drop_column("project_invitations", "can_manage_runtime_tokens")
    op.drop_column("project_members", "can_manage_team")
    op.drop_column("project_members", "can_manage_runtime_tokens")
    op.drop_column("projects", "audit_log_visibility")
