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

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    role: str
    can_push_pull_secrets: bool


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
        return ProjectAccess(project=project, role=ROLE_OWNER, can_push_pull_secrets=True)

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

    return ProjectAccess(
        project=project,
        role=membership.role,
        can_push_pull_secrets=membership.can_push_pull_secrets,
    )


def require_project_owner(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role != ROLE_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can perform this action.",
        )

    return project_access


def require_secret_access(project_access: ProjectAccess = Depends(get_project_access)) -> ProjectAccess:
    if project_access.role == ROLE_OWNER or project_access.can_push_pull_secrets:
        return project_access

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have push/pull access to this project's secrets.",
    )
