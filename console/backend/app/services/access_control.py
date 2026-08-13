from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission
from app.models.project import Project
from app.services.secret_structure import normalize_secret_path

BUILTIN_ROLE_PERMISSIONS: dict[str, list[tuple[str, str, str]]] = {
    "admin": [("*", "*", "allow")],
    "member": [
        ("secrets", "list", "allow"),
        ("secrets", "read", "allow"),
        ("secrets", "write", "allow"),
        ("folders", "read", "allow"),
        ("tags", "read", "allow"),
        ("imports", "read", "allow"),
    ],
    "viewer": [
        ("secrets", "list", "allow"),
        ("folders", "read", "allow"),
        ("tags", "read", "allow"),
        ("imports", "read", "allow"),
    ],
    "no-access": [("*", "*", "deny")],
}


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    assigned: bool
    matched_role_ids: tuple[uuid.UUID, ...]
    matched_permission_ids: tuple[uuid.UUID, ...]
    reason: str


def ensure_builtin_roles(
    db: Session, *, project_id: uuid.UUID, created_by: uuid.UUID | None
) -> list[AccessRole]:
    existing = {
        role.name: role
        for role in db.scalars(select(AccessRole).where(AccessRole.project_id == project_id)).all()
    }
    for name, permissions in BUILTIN_ROLE_PERMISSIONS.items():
        if name in existing:
            continue
        role = AccessRole(
            project_id=project_id,
            name=name,
            description=f"Built-in {name} role",
            is_builtin=True,
            created_by=created_by,
        )
        db.add(role)
        db.flush()
        for resource, action, effect in permissions:
            db.add(
                AccessRolePermission(
                    role_id=role.id,
                    resource=resource,
                    action=action,
                    effect=effect,
                    recursive=True,
                )
            )
        existing[name] = role
    db.flush()
    return sorted(existing.values(), key=lambda item: item.name)


def _path_matches(permission: AccessRolePermission, requested_path: str | None) -> bool:
    if permission.path is None:
        return True
    if requested_path is None:
        return False
    requested = normalize_secret_path(requested_path)
    allowed = normalize_secret_path(permission.path)
    if requested == allowed:
        return True
    return permission.recursive and (allowed == "/" or requested.startswith(f"{allowed}/"))


def _permission_matches(
    permission: AccessRolePermission,
    *,
    resource: str,
    action: str,
    environment_id: uuid.UUID | None,
    path: str | None,
) -> bool:
    return (
        permission.resource in {"*", resource}
        and permission.action in {"*", action}
        and (permission.environment_id is None or permission.environment_id == environment_id)
        and _path_matches(permission, path)
    )


def evaluate_permission(
    db: Session,
    *,
    project: Project,
    resource: str,
    action: str,
    environment_id: uuid.UUID | None = None,
    path: str | None = None,
    user_id: uuid.UUID | None = None,
    machine_identity_id: uuid.UUID | None = None,
) -> PermissionDecision:
    if (user_id is None) == (machine_identity_id is None):
        raise ValueError("Exactly one permission subject must be provided.")
    role_scope = AccessRole.project_id == project.id
    if project.organization_id is not None:
        role_scope = or_(role_scope, AccessRole.organization_id == project.organization_id)
    subject_filter = (
        AccessRoleAssignment.user_id == user_id
        if user_id is not None
        else AccessRoleAssignment.machine_identity_id == machine_identity_id
    )
    rows = db.execute(
        select(AccessRole, AccessRolePermission)
        .join(AccessRoleAssignment, AccessRoleAssignment.role_id == AccessRole.id)
        .join(AccessRolePermission, AccessRolePermission.role_id == AccessRole.id)
        .where(role_scope, subject_filter)
    ).all()
    assigned_role_ids = {role.id for role, _permission in rows}
    matches = [
        (role, permission)
        for role, permission in rows
        if _permission_matches(
            permission,
            resource=resource,
            action=action,
            environment_id=environment_id,
            path=path,
        )
    ]
    denied = [(role, permission) for role, permission in matches if permission.effect == "deny"]
    allowed = [(role, permission) for role, permission in matches if permission.effect == "allow"]
    selected = denied or allowed
    is_allowed = bool(allowed) and not denied
    return PermissionDecision(
        allowed=is_allowed,
        assigned=bool(assigned_role_ids),
        matched_role_ids=tuple(sorted({role.id for role, _ in selected}, key=str)),
        matched_permission_ids=tuple(sorted({permission.id for _, permission in selected}, key=str)),
        reason="explicit_deny" if denied else "explicit_allow" if allowed else "no_matching_permission",
    )


def subject_has_assignments(
    db: Session,
    *,
    project: Project,
    user_id: uuid.UUID | None = None,
    machine_identity_id: uuid.UUID | None = None,
) -> bool:
    if (user_id is None) == (machine_identity_id is None):
        return False
    role_scope = AccessRole.project_id == project.id
    if project.organization_id is not None:
        role_scope = or_(role_scope, AccessRole.organization_id == project.organization_id)
    subject_filter = (
        AccessRoleAssignment.user_id == user_id
        if user_id is not None
        else AccessRoleAssignment.machine_identity_id == machine_identity_id
    )
    return db.scalar(
        select(AccessRoleAssignment.id)
        .join(AccessRole, AccessRole.id == AccessRoleAssignment.role_id)
        .where(role_scope, subject_filter)
        .limit(1)
    ) is not None
