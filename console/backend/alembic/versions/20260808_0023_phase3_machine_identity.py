"""Add Phase 3 machine identity credentials, scopes, lockout and auth history."""

from alembic import op
import sqlalchemy as sa

revision = "20260808_0023"
down_revision = "20260808_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machine_identities", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("machine_identities", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("machine_identities", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("machine_identities", sa.Column("failed_auth_attempts", sa.Integer(), server_default="0", nullable=False))
    op.alter_column("machine_identities", "project_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("machine_identities", "environment_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key("fk_machine_identities_organization", "machine_identities", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
    op.create_check_constraint(
        "ck_machine_identities_exactly_one_scope",
        "machine_identities",
        "(project_id IS NOT NULL AND organization_id IS NULL) OR (project_id IS NULL AND organization_id IS NOT NULL)",
    )
    op.create_index("ix_machine_identities_organization_id", "machine_identities", ["organization_id"])
    op.create_table(
        "machine_identity_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("auth_method", sa.String(64), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overlap_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["machine_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", name="uq_machine_identity_credentials_client_id"),
    )
    op.create_index("ix_machine_identity_credentials_identity_id", "machine_identity_credentials", ["identity_id"])
    op.create_index("ix_machine_identity_credentials_revoked_at", "machine_identity_credentials", ["revoked_at"])
    op.execute(
        """INSERT INTO machine_identity_credentials
        (id, identity_id, name, auth_method, client_id, client_secret_hash, version, expires_at, created_by, created_at)
        SELECT id, id, 'default', 'universal-auth', client_id, client_secret_hash,
               credential_version, credential_expires_at, created_by, created_at
        FROM machine_identities"""
    )
    op.create_table(
        "machine_identity_auth_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["machine_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["credential_id"], ["machine_identity_credentials.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_machine_identity_auth_events_identity_id", "machine_identity_auth_events", ["identity_id"])
    op.create_index("ix_machine_identity_auth_events_created_at", "machine_identity_auth_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("machine_identity_auth_events")
    op.drop_table("machine_identity_credentials")
    op.drop_index("ix_machine_identities_organization_id", table_name="machine_identities")
    op.drop_constraint("ck_machine_identities_exactly_one_scope", "machine_identities", type_="check")
    op.drop_constraint("fk_machine_identities_organization", "machine_identities", type_="foreignkey")
    op.alter_column("machine_identities", "environment_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("machine_identities", "project_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("machine_identities", "failed_auth_attempts")
    op.drop_column("machine_identities", "locked_until")
    op.drop_column("machine_identities", "disabled_at")
    op.drop_column("machine_identities", "organization_id")
