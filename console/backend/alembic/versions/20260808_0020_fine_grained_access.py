"""Add organizations and fine-grained access roles."""

from alembic import op
import sqlalchemy as sa

revision = "20260808_0020"
down_revision = "20260808_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"])
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_members_user"),
    )
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"])
    op.add_column("projects", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_projects_organization", "projects", "organizations", ["organization_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_table(
        "access_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(project_id IS NOT NULL AND organization_id IS NULL) OR (project_id IS NULL AND organization_id IS NOT NULL)", name="ck_access_roles_one_scope"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_access_roles_project_name"),
        sa.UniqueConstraint("organization_id", "name", name="uq_access_roles_org_name"),
    )
    op.create_index("ix_access_roles_project_id", "access_roles", ["project_id"])
    op.create_index("ix_access_roles_organization_id", "access_roles", ["organization_id"])
    op.create_table(
        "access_role_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("path", sa.String(1000), nullable=True),
        sa.Column("recursive", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["access_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_role_permissions_role_id", "access_role_permissions", ["role_id"])
    op.create_table(
        "access_role_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("machine_identity_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(user_id IS NOT NULL AND machine_identity_id IS NULL) OR (user_id IS NULL AND machine_identity_id IS NOT NULL)", name="ck_access_role_assignments_one_subject"),
        sa.ForeignKeyConstraint(["role_id"], ["access_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["machine_identity_id"], ["machine_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "user_id", name="uq_access_role_assignments_user"),
        sa.UniqueConstraint("role_id", "machine_identity_id", name="uq_access_role_assignments_machine"),
    )
    op.create_index("ix_access_role_assignments_user_id", "access_role_assignments", ["user_id"])
    op.create_index("ix_access_role_assignments_machine_id", "access_role_assignments", ["machine_identity_id"])


def downgrade() -> None:
    op.drop_table("access_role_assignments")
    op.drop_table("access_role_permissions")
    op.drop_table("access_roles")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_constraint("fk_projects_organization", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_table("organization_members")
    op.drop_table("organizations")
