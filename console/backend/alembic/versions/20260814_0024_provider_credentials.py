"""Store encrypted provider API keys per project environment."""

from alembic import op
import sqlalchemy as sa

revision = "20260814_0024"
down_revision = "20260808_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=True),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "environment_id",
            "provider",
            name="uq_provider_credentials_project_env_provider",
        ),
    )
    op.create_index(
        "ix_provider_credentials_project_id",
        "provider_credentials",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_provider_credentials_environment_id",
        "provider_credentials",
        ["environment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_credentials_environment_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_project_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
