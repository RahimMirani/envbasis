"""Add encrypted runtime token storage and token sharing."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260312_0002"
down_revision = "20260311_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runtime_tokens", sa.Column("encrypted_token", sa.LargeBinary(), nullable=True))

    op.create_table(
        "runtime_token_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("runtime_token_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("shared_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["runtime_token_id"], ["runtime_tokens.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shared_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runtime_token_id", "user_id", name="uq_runtime_token_shares_token_user"),
    )
    op.create_index(
        "ix_runtime_token_shares_runtime_token_id",
        "runtime_token_shares",
        ["runtime_token_id"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_token_shares_user_id",
        "runtime_token_shares",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_token_shares_user_id", table_name="runtime_token_shares")
    op.drop_index("ix_runtime_token_shares_runtime_token_id", table_name="runtime_token_shares")
    op.drop_table("runtime_token_shares")
    op.drop_column("runtime_tokens", "encrypted_token")
