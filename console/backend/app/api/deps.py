from __future__ import annotations

from dataclasses import dataclass
import uuid
from fnmatch import fnmatchcase

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthIdentity, build_auth_identity, decode_access_token
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services.audit import write_audit_log
from app.services.access_control import evaluate_permission, subject_has_assignments
from app.services.machine_identities import resolve_machine_identity_from_access_token
from app.models.machine_identity import MachineIdentity

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    role: str
    can_push_pull_secrets: bool
    can_manage_runtime_tokens: bool
    can_manage_team: bool
    can_view_audit_logs: bool
    subject_user_id: uuid.UUID | None = None
    subject_machine_id: uuid.UUID | None = None
    uses_rbac: bool = False
    machine_environment_id: uuid.UUID | None = None
    machine_allowed_actions: tuple[str, ...] = ()
    machine_allowed_secret_keys: tuple[str, ...] | None = None


def _resolve_identity(
    *,
    credentials: HTTPAuthorizationCredentials | None,
) -> AuthIdentity:
    if credentials is not None:
        try:
            return build_auth_identity(decode_access_token(credentials.credentials))
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        identity = _resolve_identity(credentials=credentials)
    except HTTPException as user_error:
        if credentials is None:
            raise
        try:
            machine = resolve_machine_identity_from_access_token(db, access_token=credentials.credentials)
        except (ValueError, RuntimeError):
            raise user_error
        user = db.get(User, machine.id)
        if user is None:
            user = User(id=machine.id, email=f"machine-{machine.id}@identities.envbasis.internal")
            db.add(user)
            db.commit()
            db.refresh(user)
        setattr(user, "_machine_identity_id", machine.id)
        return user

    user = db.get(User, identity.user_id)
    if user is None:
        user = User(id=identity.user_id, email=identity.email)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    if user.email != identity.email:
        user.email = identity.email
        db.commit()
        db.refresh(user)

    return user


def get_project_access(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    machine_identity_id = getattr(current_user, "_machine_identity_id", None)
    if machine_identity_id is not None:
        machine = db.get(MachineIdentity, machine_identity_id)
        if machine is None or not (
            machine.project_id == project.id
            or (machine.organization_id is not None and machine.organization_id == project.organization_id)
        ):
            raise HTTPException(status_code=403, detail="Machine identity cannot access this project.")
        uses_rbac = subject_has_assignments(db, project=project, machine_identity_id=machine.id)
        if machine.organization_id is not None and not uses_rbac:
            raise HTTPException(status_code=403, detail="Machine identity has no role in this project.")
        can_read = "secrets:read" in machine.allowed_actions
        return ProjectAccess(
            project=project,
            role=ROLE_MEMBER,
            can_push_pull_secrets=can_read,
            can_manage_runtime_tokens=False,
            can_manage_team=False,
            can_view_audit_logs=False,
            subject_machine_id=machine.id,
            uses_rbac=uses_rbac,
            machine_environment_id=machine.environment_id,
            machine_allowed_actions=tuple(machine.allowed_actions or []),
            machine_allowed_secret_keys=(tuple(machine.allowed_secret_keys) if machine.allowed_secret_keys is not None else None),
        )

    if project.owner_id == current_user.id:
        return ProjectAccess(
            project=project,
            role=ROLE_OWNER,
            can_push_pull_secrets=True,
            can_manage_runtime_tokens=True,
            can_manage_team=True,
            can_view_audit_logs=True,
            subject_user_id=current_user.id,
        )

    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    uses_rbac = subject_has_assignments(db, project=project, user_id=current_user.id)
    if membership is None and not uses_rbac:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project.",
        )

    if project.audit_log_visibility == "members":
        can_view_audit_logs = True
    elif project.audit_log_visibility == "specific":
        can_view_audit_logs = bool(membership and membership.can_view_audit_logs)
    else:
        can_view_audit_logs = False

    return ProjectAccess(
        project=project,
        role=membership.role if membership is not None else ROLE_MEMBER,
        can_push_pull_secrets=bool(membership and membership.can_push_pull_secrets),
        can_manage_runtime_tokens=bool(membership and membership.can_manage_runtime_tokens),
        can_manage_team=bool(membership and membership.can_manage_team),
        can_view_audit_logs=can_view_audit_logs,
        subject_user_id=current_user.id,
        uses_rbac=uses_rbac,
    )


def require_project_owner(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can perform this action.",
        )

    return project_access


def require_secret_management(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.subject_machine_id is not None or project_access.uses_rbac or project_access.can_push_pull_secrets:
        return project_access

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this project's secrets.",
    )


def enforce_project_permission(
    db: Session,
    *,
    project_access: ProjectAccess,
    resource: str,
    action: str,
    environment_id: uuid.UUID | None = None,
    path: str | None = None,
    legacy_allowed: bool = False,
) -> None:
    if project_access.role == ROLE_OWNER:
        return
    if project_access.subject_machine_id is not None:
        if project_access.machine_environment_id is not None and environment_id is not None and project_access.machine_environment_id != environment_id:
            raise HTTPException(status_code=403, detail="Machine identity cannot access this environment.")
        if resource == "secrets" and action in {"read", "list"} and "secrets:read" not in project_access.machine_allowed_actions:
            raise HTTPException(status_code=403, detail="Machine identity cannot read secrets.")
        if resource == "secrets" and action == "write":
            raise HTTPException(status_code=403, detail="Machine identity is read-only.")
    if project_access.uses_rbac and project_access.subject_user_id is not None:
        decision = evaluate_permission(
            db,
            project=project_access.project,
            user_id=project_access.subject_user_id,
            resource=resource,
            action=action,
            environment_id=environment_id,
            path=path,
        )
        if decision.allowed:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {resource}:{action} ({decision.reason}).",
        )
    if project_access.uses_rbac and project_access.subject_machine_id is not None:
        decision = evaluate_permission(
            db,
            project=project_access.project,
            machine_identity_id=project_access.subject_machine_id,
            resource=resource,
            action=action,
            environment_id=environment_id,
            path=path,
        )
        if decision.allowed:
            return
        raise HTTPException(status_code=403, detail=f"Permission denied: {resource}:{action} ({decision.reason}).")
    if legacy_allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Permission denied: {resource}:{action}.",
    )


def machine_secret_key_allowed(project_access: ProjectAccess, key: str) -> bool:
    if project_access.subject_machine_id is None or project_access.machine_allowed_secret_keys is None:
        return True
    return any(fnmatchcase(key, pattern) for pattern in project_access.machine_allowed_secret_keys)


def enforce_machine_secret_key(project_access: ProjectAccess, key: str) -> None:
    if not machine_secret_key_allowed(project_access, key):
        raise HTTPException(status_code=403, detail="Machine identity cannot access this secret key.")


def require_runtime_token_management(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.can_manage_runtime_tokens:
        return project_access

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this project's runtime tokens.",
    )


def require_team_management(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.can_manage_team:
        return project_access

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this project's team.",
    )


def require_audit_log_access(
    project_access: ProjectAccess = Depends(get_project_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.can_view_audit_logs:
        return project_access

    if project_access.role == ROLE_MEMBER:
        write_audit_log(
            db,
            project_id=project_access.project.id,
            user_id=current_user.id,
            action="audit_logs.access_denied",
            metadata={"reason": "visibility"},
        )
        db.commit()

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to view this project's audit logs.",
    )
