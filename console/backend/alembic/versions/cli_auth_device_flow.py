"""Add CLI auth sessions, refresh tokens, and audit logs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260318_0006"
down_revision = "20260314_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cli_auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_code_hash", sa.String(length=128), nullable=False),
        sa.Column("user_code", sa.String(length=32), nullable=False),
        sa.Column("user_code_normalized", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("cli_version", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("denied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied', 'expired', 'consumed')",
            name="ck_cli_auth_sessions_status_valid",
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cli_auth_sessions_device_code_hash",
        "cli_auth_sessions",
        ["device_code_hash"],
        unique=True,
    )
    op.create_index(
        "uq_cli_auth_sessions_user_code_normalized",
        "cli_auth_sessions",
        ["user_code_normalized"],
        unique=True,
    )
    op.create_index("ix_cli_auth_sessions_status", "cli_auth_sessions", ["status"], unique=False)
    op.create_index("ix_cli_auth_sessions_expires_at", "cli_auth_sessions", ["expires_at"], unique=False)
    op.create_index(
        "ix_cli_auth_sessions_approved_by_user_id",
        "cli_auth_sessions",
        ["approved_by_user_id"],
        unique=False,
    )

    op.create_table(
        "cli_auth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cli_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_token_id", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("cli_version", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cli_auth_session_id"], ["cli_auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["replaced_by_token_id"], ["cli_auth_refresh_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cli_auth_refresh_tokens_token_hash",
        "cli_auth_refresh_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_cli_auth_refresh_tokens_user_id",
        "cli_auth_refresh_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_cli_auth_refresh_tokens_session_id",
        "cli_auth_refresh_tokens",
        ["cli_auth_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_cli_auth_refresh_tokens_expires_at",
        "cli_auth_refresh_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_cli_auth_refresh_tokens_revoked_at",
        "cli_auth_refresh_tokens",
        ["revoked_at"],
        unique=False,
    )

    op.create_table(
        "cli_auth_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cli_auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cli_auth_session_id"], ["cli_auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cli_auth_audit_logs_cli_auth_session_id",
        "cli_auth_audit_logs",
        ["cli_auth_session_id"],
        unique=False,
    )
    op.create_index("ix_cli_auth_audit_logs_user_id", "cli_auth_audit_logs", ["user_id"], unique=False)
    op.create_index("ix_cli_auth_audit_logs_action", "cli_auth_audit_logs", ["action"], unique=False)
    op.create_index("ix_cli_auth_audit_logs_created_at", "cli_auth_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cli_auth_audit_logs_created_at", table_name="cli_auth_audit_logs")
    op.drop_index("ix_cli_auth_audit_logs_action", table_name="cli_auth_audit_logs")
    op.drop_index("ix_cli_auth_audit_logs_user_id", table_name="cli_auth_audit_logs")
    op.drop_index("ix_cli_auth_audit_logs_cli_auth_session_id", table_name="cli_auth_audit_logs")
    op.drop_table("cli_auth_audit_logs")

    op.drop_index("ix_cli_auth_refresh_tokens_revoked_at", table_name="cli_auth_refresh_tokens")
    op.drop_index("ix_cli_auth_refresh_tokens_expires_at", table_name="cli_auth_refresh_tokens")
    op.drop_index("ix_cli_auth_refresh_tokens_session_id", table_name="cli_auth_refresh_tokens")
    op.drop_index("ix_cli_auth_refresh_tokens_user_id", table_name="cli_auth_refresh_tokens")
    op.drop_index("uq_cli_auth_refresh_tokens_token_hash", table_name="cli_auth_refresh_tokens")
    op.drop_table("cli_auth_refresh_tokens")

    op.drop_index("ix_cli_auth_sessions_approved_by_user_id", table_name="cli_auth_sessions")
    op.drop_index("ix_cli_auth_sessions_expires_at", table_name="cli_auth_sessions")
    op.drop_index("ix_cli_auth_sessions_status", table_name="cli_auth_sessions")
    op.drop_index("uq_cli_auth_sessions_user_code_normalized", table_name="cli_auth_sessions")
    op.drop_index("uq_cli_auth_sessions_device_code_hash", table_name="cli_auth_sessions")
    op.drop_table("cli_auth_sessions")
