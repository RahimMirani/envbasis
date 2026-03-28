from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import (
    ROLE_MEMBER,
    ROLE_OWNER,
    ProjectAccess,
    get_current_user,
    get_project_access,
    require_project_owner,
)
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.runtime_token import RuntimeToken
from app.models.runtime_token_share import RuntimeTokenShare
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.environment import EnvironmentCreate, EnvironmentRead
from app.schemas.member import (
    MemberAccessUpdateRequest,
    MemberInviteRequest,
    MemberRevokeRequest,
    ProjectMemberRead,
)
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.audit import write_audit_log

router = APIRouter(prefix="/projects")


def _get_project_stats_map(
    db: Session,
    *,
    project_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, object]]:
    if not project_ids:
        return {}

    environment_counts = (
        select(
            Environment.project_id.label("project_id"),
            func.count(Environment.id).label("environment_count"),
        )
        .where(Environment.project_id.in_(project_ids))
        .group_by(Environment.project_id)
        .subquery()
    )
    member_counts = (
        select(
            ProjectMember.project_id.label("project_id"),
            func.count(ProjectMember.id).label("member_count"),
        )
        .where(ProjectMember.project_id.in_(project_ids))
        .group_by(ProjectMember.project_id)
        .subquery()
    )
    runtime_token_counts = (
        select(
            RuntimeToken.project_id.label("project_id"),
            func.count(RuntimeToken.id).label("runtime_token_count"),
        )
        .where(RuntimeToken.project_id.in_(project_ids))
        .group_by(RuntimeToken.project_id)
        .subquery()
    )
    activity_timestamps = (
        select(
            AuditLog.project_id.label("project_id"),
            func.max(AuditLog.created_at).label("last_activity_at"),
        )
        .where(AuditLog.project_id.in_(project_ids))
        .group_by(AuditLog.project_id)
        .subquery()
    )

    rows = db.execute(
        select(
            Project.id,
            func.coalesce(environment_counts.c.environment_count, 0),
            func.coalesce(member_counts.c.member_count, 0),
            func.coalesce(runtime_token_counts.c.runtime_token_count, 0),
            activity_timestamps.c.last_activity_at,
        )
        .outerjoin(environment_counts, environment_counts.c.project_id == Project.id)
        .outerjoin(member_counts, member_counts.c.project_id == Project.id)
        .outerjoin(runtime_token_counts, runtime_token_counts.c.project_id == Project.id)
        .outerjoin(activity_timestamps, activity_timestamps.c.project_id == Project.id)
        .where(Project.id.in_(project_ids))
    ).all()

    return {
        project_id: {
            "environment_count": environment_count,
            "member_count": member_count,
            "runtime_token_count": runtime_token_count,
            "last_activity_at": last_activity_at,
        }
        for project_id, environment_count, member_count, runtime_token_count, last_activity_at in rows
    }


def _serialize_project(
    project: Project,
    role: str,
    stats_map: dict[uuid.UUID, dict[str, object]] | None = None,
) -> ProjectRead:
    stats = (stats_map or {}).get(project.id, {})
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        role=role,
        created_at=project.created_at,
        environment_count=int(stats.get("environment_count", 0)),
        member_count=int(stats.get("member_count", 0)),
        runtime_token_count=int(stats.get("runtime_token_count", 0)),
        last_activity_at=stats.get("last_activity_at"),
    )


def _serialize_member(member: ProjectMember, user: User) -> ProjectMemberRead:
    return ProjectMemberRead(
        user_id=user.id,
        email=user.email,
        role=member.role,
        can_push_pull_secrets=member.can_push_pull_secrets,
        joined_at=member.created_at,
    )


def _get_project_member_or_404(db: Session, *, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember:
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this project.",
        )

    return membership


def _get_shared_runtime_tokens_for_member(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[RuntimeToken]:
    return list(
        db.scalars(
            select(RuntimeToken)
            .join(RuntimeTokenShare, RuntimeTokenShare.runtime_token_id == RuntimeToken.id)
            .where(
                RuntimeToken.project_id == project_id,
                RuntimeTokenShare.user_id == user_id,
            )
            .order_by(RuntimeToken.name.asc())
        ).all()
    )


def _get_revealed_runtime_tokens_for_member(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    shared_tokens: list[RuntimeToken],
) -> list[RuntimeToken]:
    if not shared_tokens:
        return []

    shared_tokens_by_id = {str(token.id): token for token in shared_tokens}
    reveal_logs = db.scalars(
        select(AuditLog).where(
            AuditLog.project_id == project_id,
            AuditLog.user_id == user_id,
            AuditLog.action == "runtime_token.revealed",
        )
    ).all()

    revealed_token_ids: set[str] = set()
    for log in reveal_logs:
        token_id = (log.metadata_json or {}).get("token_id")
        if token_id in shared_tokens_by_id:
            revealed_token_ids.add(token_id)

    return [shared_tokens_by_id[token_id] for token_id in revealed_token_ids]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectRead:
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project name cannot be empty.",
        )
    description = payload.description.strip() if payload.description else None
    if description == "":
        description = None

    project = Project(name=project_name, description=description, owner_id=current_user.id)
    db.add(project)
    db.flush()

    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=current_user.id,
            role=ROLE_OWNER,
            can_push_pull_secrets=True,
            invited_by=current_user.id,
        )
    )
    write_audit_log(
        db,
        project_id=project.id,
        user_id=current_user.id,
        action="project.created",
        metadata={"project_name": project.name},
    )
    db.commit()
    db.refresh(project)
    stats_map = _get_project_stats_map(db, project_ids=[project.id])
    return _serialize_project(project, ROLE_OWNER, stats_map)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectRead]:
    membership = aliased(ProjectMember)
    stmt = (
        select(Project, membership.role)
        .outerjoin(
            membership,
            and_(
                membership.project_id == Project.id,
                membership.user_id == current_user.id,
            ),
        )
        .where(
            or_(
                Project.owner_id == current_user.id,
                membership.user_id == current_user.id,
            )
        )
        .order_by(Project.created_at.desc())
    )

    rows = db.execute(stmt).all()
    stats_map = _get_project_stats_map(db, project_ids=[project.id for project, _ in rows])
    return [
        _serialize_project(
            project,
            ROLE_OWNER if project.owner_id == current_user.id else role or ROLE_MEMBER,
            stats_map,
        )
        for project, role in rows
    ]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> ProjectRead:
    stats_map = _get_project_stats_map(
        db,
        project_ids=[project_access.project.id],
    )
    return _serialize_project(project_access.project, project_access.role, stats_map)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    payload: ProjectUpdate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectRead:
    metadata: dict[str, str | None] = {}

    if payload.name is not None:
        project_name = payload.name.strip()
        if not project_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project name cannot be empty.",
            )
        project_access.project.name = project_name
        metadata["name"] = project_name

    if payload.description is not None:
        description = payload.description.strip() or None
        project_access.project.description = description
        metadata["description"] = description

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="project.updated",
        metadata=metadata,
    )
    db.commit()
    db.refresh(project_access.project)
    stats_map = _get_project_stats_map(db, project_ids=[project_access.project.id])
    return _serialize_project(project_access.project, project_access.role, stats_map)


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> MessageResponse:
    project_name = project_access.project.name
    db.delete(project_access.project)
    db.commit()
    return MessageResponse(detail=f"Project '{project_name}' deleted.")


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_environment(
    payload: EnvironmentCreate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Environment:
    environment_name = payload.name.strip()
    if not environment_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Environment name cannot be empty.",
        )

    existing_environment = db.scalar(
        select(Environment).where(
            Environment.project_id == project_access.project.id,
            Environment.name == environment_name,
        )
    )
    if existing_environment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Environment already exists for this project.",
        )

    environment = Environment(project_id=project_access.project.id, name=environment_name)
    db.add(environment)
    db.flush()
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="environment.created",
        metadata={"environment_name": environment.name},
    )
    db.commit()
    db.refresh(environment)
    return environment


@router.get("/{project_id}/environments", response_model=list[EnvironmentRead])
def list_environments(
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> list[Environment]:
    environments = db.scalars(
        select(Environment)
        .where(Environment.project_id == project_access.project.id)
        .order_by(Environment.created_at.asc())
    ).all()
    return list(environments)


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
def list_members(
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> list[ProjectMemberRead]:
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_access.project.id)
        .order_by(ProjectMember.created_at.asc())
    ).all()

    members = {
        user.id: _serialize_member(member, user)
        for member, user in rows
    }

    if project_access.project.owner_id not in members:
        owner = db.get(User, project_access.project.owner_id)
        if owner is not None:
            members[owner.id] = ProjectMemberRead(
                user_id=owner.id,
                email=owner.email,
                role=ROLE_OWNER,
                can_push_pull_secrets=True,
                joined_at=project_access.project.created_at,
            )

    return list(members.values())


@router.post(
    "/{project_id}/invite",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    payload: MemberInviteRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    invited_email = payload.email.strip().lower()
    invited_user = db.scalar(select(User).where(User.email == invited_email))
    if invited_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User must authenticate once before they can be added to a project.",
        )

    if invited_user.id == project_access.project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project owner is already part of this project.",
        )

    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_access.project.id,
            ProjectMember.user_id == invited_user.id,
        )
    )
    if membership is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a project member.",
        )

    membership = ProjectMember(
        project_id=project_access.project.id,
        user_id=invited_user.id,
        role=payload.role,
        can_push_pull_secrets=payload.can_push_pull_secrets,
        invited_by=current_user.id,
    )
    db.add(membership)
    db.flush()
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="member.invited",
        metadata={
            "email": invited_user.email,
            "role": payload.role,
            "can_push_pull_secrets": payload.can_push_pull_secrets,
        },
    )
    db.commit()
    db.refresh(membership)
    return _serialize_member(membership, invited_user)


@router.post("/{project_id}/members/access", response_model=ProjectMemberRead)
def update_member_secret_access(
    payload: MemberAccessUpdateRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    member_email = payload.email.strip().lower()
    member_user = db.scalar(select(User).where(User.email == member_email))
    if member_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if member_user.id == project_access.project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project owner secret access cannot be changed.",
        )

    membership = _get_project_member_or_404(
        db,
        project_id=project_access.project.id,
        user_id=member_user.id,
    )
    membership.can_push_pull_secrets = payload.can_push_pull_secrets
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="member.secret_access.updated",
        metadata={
            "email": member_user.email,
            "can_push_pull_secrets": payload.can_push_pull_secrets,
        },
    )
    db.commit()
    db.refresh(membership)
    return _serialize_member(membership, member_user)


@router.post("/{project_id}/revoke", response_model=MessageResponse)
def revoke_member(
    payload: MemberRevokeRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    revoked_email = payload.email.strip().lower()
    revoked_user = db.scalar(select(User).where(User.email == revoked_email))
    if revoked_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if revoked_user.id == project_access.project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project owner cannot be revoked.",
        )

    membership = _get_project_member_or_404(
        db,
        project_id=project_access.project.id,
        user_id=revoked_user.id,
    )
    shared_tokens = _get_shared_runtime_tokens_for_member(
        db,
        project_id=project_access.project.id,
        user_id=revoked_user.id,
    )
    revealed_shared_tokens = _get_revealed_runtime_tokens_for_member(
        db,
        project_id=project_access.project.id,
        user_id=revoked_user.id,
        shared_tokens=shared_tokens,
    )
    if shared_tokens and payload.shared_token_action is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "shared_runtime_token_confirmation_required",
                "message": "This member has shared runtime tokens. Retry with shared_token_action set to 'keep_active' or 'revoke_tokens'.",
                "shared_token_count": len(shared_tokens),
                "shared_tokens": [
                    {"id": str(token.id), "name": token.name}
                    for token in shared_tokens
                ],
                "revealed_shared_tokens": [
                    {"id": str(token.id), "name": token.name}
                    for token in revealed_shared_tokens
                ],
            },
        )
    if payload.shared_token_action == "keep_active" and revealed_shared_tokens:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "revealed_runtime_tokens_require_revocation",
                "message": "This member already revealed one or more shared runtime tokens. Keeping them active is unsafe. Revoke or rotate those tokens instead.",
                "revealed_shared_token_count": len(revealed_shared_tokens),
                "revealed_shared_tokens": [
                    {"id": str(token.id), "name": token.name}
                    for token in revealed_shared_tokens
                ],
            },
        )

    token_ids = [token.id for token in shared_tokens]
    share_rows = []
    if token_ids:
        share_rows = list(
            db.scalars(
                select(RuntimeTokenShare).where(
                    RuntimeTokenShare.user_id == revoked_user.id,
                    RuntimeTokenShare.runtime_token_id.in_(token_ids),
                )
            ).all()
        )
    for share in share_rows:
        db.delete(share)

    revoked_token_count = 0
    if payload.shared_token_action == "revoke_tokens":
        for token in shared_tokens:
            revoked_token_count += 1
            write_audit_log(
                db,
                project_id=project_access.project.id,
                environment_id=token.environment_id,
                user_id=current_user.id,
                action="runtime_token.revoked",
                metadata={
                    "token_id": str(token.id),
                    "name": token.name,
                    "reason": "member_removed",
                    "removed_member_email": revoked_user.email,
                },
            )
            db.delete(token)

    db.delete(membership)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="member.revoked",
        metadata={
            "email": revoked_user.email,
            "removed_shared_token_count": len(share_rows),
            "removed_shared_token_names": [token.name for token in shared_tokens],
            "revealed_shared_token_names": [token.name for token in revealed_shared_tokens],
            "shared_token_action": payload.shared_token_action or "not_applicable",
            "revoked_runtime_token_count": revoked_token_count,
        },
    )
    db.commit()
    detail = "Member access revoked."
    if share_rows:
        detail += f" Removed {len(share_rows)} runtime token share(s)."
    if revoked_token_count:
        detail += f" Revoked {revoked_token_count} underlying runtime token(s)."
    return MessageResponse(detail=detail)
