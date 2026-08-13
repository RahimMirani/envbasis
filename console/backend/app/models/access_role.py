from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AccessRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "access_roles"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND organization_id IS NULL) OR "
            "(project_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_access_roles_one_scope",
        ),
        UniqueConstraint("project_id", "name", name="uq_access_roles_project_name"),
        UniqueConstraint("organization_id", "name", name="uq_access_roles_org_name"),
        Index("ix_access_roles_project_id", "project_id"),
        Index("ix_access_roles_organization_id", "organization_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccessRolePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "access_role_permissions"
    __table_args__ = (Index("ix_access_role_permissions_role_id", "role_id"),)

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_roles.id", ondelete="CASCADE"), nullable=False
    )
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=True
    )
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AccessRoleAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "access_role_assignments"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND machine_identity_id IS NULL) OR "
            "(user_id IS NULL AND machine_identity_id IS NOT NULL)",
            name="ck_access_role_assignments_one_subject",
        ),
        UniqueConstraint("role_id", "user_id", name="uq_access_role_assignments_user"),
        UniqueConstraint(
            "role_id", "machine_identity_id", name="uq_access_role_assignments_machine"
        ),
        Index("ix_access_role_assignments_user_id", "user_id"),
        Index("ix_access_role_assignments_machine_id", "machine_identity_id"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_roles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    machine_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("machine_identities.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
