from __future__ import annotations

from dataclasses import dataclass
import uuid

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
    identity = _resolve_identity(
        credentials=credentials,
    )

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

    if project.owner_id == current_user.id:
        return ProjectAccess(
            project=project,
            role=ROLE_OWNER,
            can_push_pull_secrets=True,
            can_manage_runtime_tokens=True,
            can_manage_team=True,
            can_view_audit_logs=True,
        )

    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project.",
        )

    if project.audit_log_visibility == "members":
        can_view_audit_logs = True
    elif project.audit_log_visibility == "specific":
        can_view_audit_logs = membership.can_view_audit_logs
    else:
        can_view_audit_logs = False

    return ProjectAccess(
        project=project,
        role=membership.role,
        can_push_pull_secrets=membership.can_push_pull_secrets,
        can_manage_runtime_tokens=membership.can_manage_runtime_tokens,
        can_manage_team=membership.can_manage_team,
        can_view_audit_logs=can_view_audit_logs,
    )


def require_project_owner(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can perform this action.",
        )

    return project_access


def require_secret_management(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.can_push_pull_secrets:
        return project_access

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this project's secrets.",
    )


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
