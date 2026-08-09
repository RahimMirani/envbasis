from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_project_owner
from app.db.session import get_db
from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission
from app.models.environment import Environment
from app.models.machine_identity import MachineIdentity
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.schemas.access_control import (
    AccessRoleCreate,
    AccessRoleRead,
    AccessRoleUpdate,
    OrganizationCreate,
    OrganizationRead,
    PermissionSimulationRead,
    PermissionSimulationRequest,
    RoleAssignmentCreate,
    RoleAssignmentRead,
    RolePermissionRead,
)
from app.services.access_control import ensure_builtin_roles, evaluate_permission
from app.services.audit import write_audit_log
from app.services.secret_structure import normalize_secret_path

router = APIRouter()


def _serialize_role(db: Session, role: AccessRole) -> AccessRoleRead:
    permissions = db.scalars(
        select(AccessRolePermission)
        .where(AccessRolePermission.role_id == role.id)
        .order_by(AccessRolePermission.resource, AccessRolePermission.action)
    ).all()
    return AccessRoleRead(
        id=role.id,
        project_id=role.project_id,
        organization_id=role.organization_id,
        name=role.name,
        description=role.description,
        is_builtin=role.is_builtin,
        created_at=role.created_at,
        permissions=[
            RolePermissionRead(
                id=item.id,
                resource=item.resource,
                action=item.action,
                effect=item.effect,
                environment_id=item.environment_id,
                path=item.path,
                recursive=item.recursive,
            )
            for item in permissions
        ],
    )


def _validate_permissions(db: Session, *, project_id: uuid.UUID, permissions) -> None:
    for permission in permissions:
        if permission.environment_id is not None:
            environment = db.get(Environment, permission.environment_id)
            if environment is None or environment.project_id != project_id:
                raise HTTPException(status_code=422, detail="Permission environment is not in this project.")
        if permission.path is not None:
            try:
                permission.path = normalize_secret_path(permission.path)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc


def _replace_permissions(db: Session, *, role: AccessRole, permissions) -> None:
    db.execute(delete(AccessRolePermission).where(AccessRolePermission.role_id == role.id))
    for item in permissions:
        db.add(AccessRolePermission(role_id=role.id, **item.model_dump()))


@router.post("/organizations", response_model=OrganizationRead, status_code=201)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationRead:
    organization = Organization(name=payload.name.strip(), owner_id=current_user.id)
    db.add(organization)
    db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=current_user.id))
    db.commit()
    db.refresh(organization)
    return OrganizationRead.model_validate(organization, from_attributes=True)


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[OrganizationRead]:
    organizations = db.scalars(
        select(Organization)
        .outerjoin(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(or_(Organization.owner_id == current_user.id, OrganizationMember.user_id == current_user.id))
        .distinct()
        .order_by(Organization.name)
    ).all()
    return [OrganizationRead.model_validate(item, from_attributes=True) for item in organizations]


@router.get("/projects/{project_id}/access-roles", response_model=list[AccessRoleRead])
def list_access_roles(
    project_access: ProjectAccess = Depends(require_project_owner), db: Session = Depends(get_db)
) -> list[AccessRoleRead]:
    ensure_builtin_roles(db, project_id=project_access.project.id, created_by=project_access.project.owner_id)
    db.commit()
    scope = AccessRole.project_id == project_access.project.id
    if project_access.project.organization_id is not None:
        scope = or_(scope, AccessRole.organization_id == project_access.project.organization_id)
    roles = db.scalars(select(AccessRole).where(scope).order_by(AccessRole.name)).all()
    return [_serialize_role(db, role) for role in roles]


@router.post("/projects/{project_id}/access-roles", response_model=AccessRoleRead, status_code=201)
def create_access_role(
    payload: AccessRoleCreate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessRoleRead:
    project = project_access.project
    if payload.organization_id is not None and payload.organization_id != project.organization_id:
        raise HTTPException(status_code=422, detail="Organization role must belong to the project's organization.")
    if payload.organization_id is not None:
        organization = db.get(Organization, payload.organization_id)
        if organization is None or organization.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the organization owner can create this role.")
    _validate_permissions(db, project_id=project.id, permissions=payload.permissions)
    role = AccessRole(
        project_id=None if payload.organization_id else project.id,
        organization_id=payload.organization_id,
        name=payload.name.strip(),
        description=payload.description,
        is_builtin=False,
        created_by=current_user.id,
    )
    db.add(role)
    try:
        db.flush()
        _replace_permissions(db, role=role, permissions=payload.permissions)
        write_audit_log(db, project_id=project.id, user_id=current_user.id, action="access_role.created", metadata={"role_id": str(role.id), "name": role.name})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A role with this name already exists in the scope.") from exc
    db.refresh(role)
    return _serialize_role(db, role)


def _get_project_role_or_404(db: Session, *, project, role_id: uuid.UUID) -> AccessRole:
    role = db.get(AccessRole, role_id)
    valid = role is not None and (
        role.project_id == project.id
        or (project.organization_id is not None and role.organization_id == project.organization_id)
    )
    if not valid:
        raise HTTPException(status_code=404, detail="Access role not found.")
    return role


@router.patch("/projects/{project_id}/access-roles/{role_id}", response_model=AccessRoleRead)
def update_access_role(
    role_id: uuid.UUID,
    payload: AccessRoleUpdate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessRoleRead:
    role = _get_project_role_or_404(db, project=project_access.project, role_id=role_id)
    if role.is_builtin:
        raise HTTPException(status_code=409, detail="Built-in roles cannot be modified.")
    if payload.name is not None:
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        _validate_permissions(db, project_id=project_access.project.id, permissions=payload.permissions)
        _replace_permissions(db, role=role, permissions=payload.permissions)
    write_audit_log(db, project_id=project_access.project.id, user_id=current_user.id, action="access_role.updated", metadata={"role_id": str(role.id)})
    db.commit()
    db.refresh(role)
    return _serialize_role(db, role)


@router.delete("/projects/{project_id}/access-roles/{role_id}", status_code=204)
def delete_access_role(
    role_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> Response:
    role = _get_project_role_or_404(db, project=project_access.project, role_id=role_id)
    if role.is_builtin:
        raise HTTPException(status_code=409, detail="Built-in roles cannot be deleted.")
    db.delete(role)
    db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/access-assignments", response_model=list[RoleAssignmentRead])
def list_role_assignments(
    project_access: ProjectAccess = Depends(require_project_owner), db: Session = Depends(get_db)
) -> list[RoleAssignmentRead]:
    project = project_access.project
    scope = AccessRole.project_id == project.id
    if project.organization_id is not None:
        scope = or_(scope, AccessRole.organization_id == project.organization_id)
    items = db.scalars(
        select(AccessRoleAssignment).join(AccessRole).where(scope).order_by(AccessRoleAssignment.created_at)
    ).all()
    return [RoleAssignmentRead.model_validate(item, from_attributes=True) for item in items]


@router.post("/projects/{project_id}/access-assignments", response_model=RoleAssignmentRead, status_code=201)
def create_role_assignment(
    payload: RoleAssignmentCreate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoleAssignmentRead:
    role = _get_project_role_or_404(db, project=project_access.project, role_id=payload.role_id)
    if role.organization_id is not None:
        organization = db.get(Organization, role.organization_id)
        if organization is None or organization.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the organization owner can assign organization roles.")
    if payload.user_id is not None and db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.machine_identity_id is not None:
        machine = db.get(MachineIdentity, payload.machine_identity_id)
        if machine is None or machine.project_id != project_access.project.id:
            raise HTTPException(status_code=404, detail="Machine identity not found.")
    assignment = AccessRoleAssignment(
        role_id=role.id,
        user_id=payload.user_id,
        machine_identity_id=payload.machine_identity_id,
        created_by=current_user.id,
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This role is already assigned to the subject.") from exc
    db.refresh(assignment)
    return RoleAssignmentRead.model_validate(assignment, from_attributes=True)


@router.delete("/projects/{project_id}/access-assignments/{assignment_id}", status_code=204)
def delete_role_assignment(
    assignment_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> Response:
    assignment = db.get(AccessRoleAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Role assignment not found.")
    _get_project_role_or_404(db, project=project_access.project, role_id=assignment.role_id)
    db.delete(assignment)
    db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/permissions/simulate", response_model=PermissionSimulationRead)
def simulate_permission(
    payload: PermissionSimulationRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> PermissionSimulationRead:
    decision = evaluate_permission(
        db,
        project=project_access.project,
        user_id=payload.user_id,
        machine_identity_id=payload.machine_identity_id,
        resource=payload.resource,
        action=payload.action,
        environment_id=payload.environment_id,
        path=payload.path,
    )
    return PermissionSimulationRead(
        allowed=decision.allowed,
        assigned=decision.assigned,
        reason=decision.reason,
        matched_role_ids=list(decision.matched_role_ids),
        matched_permission_ids=list(decision.matched_permission_ids),
    )
