"""Add per-member audit log visibility, can_view_audit_logs, and runtime_token_share.can_manage."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_0009"
down_revision = "97ae7c2f088f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_members",
        sa.Column(
            "can_view_audit_logs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "project_invitations",
        sa.Column(
            "can_view_audit_logs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "runtime_token_shares",
        sa.Column(
            "can_manage",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("runtime_token_shares", "can_manage")
    op.drop_column("project_invitations", "can_view_audit_logs")
    op.drop_column("project_members", "can_view_audit_logs")
