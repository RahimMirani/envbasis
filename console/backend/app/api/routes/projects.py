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
    require_team_management,
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
from app.schemas.environment import EnvironmentCreate, EnvironmentRead, EnvironmentUpdate
from app.schemas.invitation import InviteMemberResponse, ProjectInvitationRead
from app.schemas.member import (
    MemberBulkPermissionUpdateRequest,
    MemberBulkRevokeRequest,
    MemberInviteRequest,
    MemberPermissionUpdateRequest,
    MemberRevokeRequest,
    ProjectMemberRead,
)
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.webhooks import dispatch_webhooks, get_webhooks_for_event
from app.services.invitation_service import (
    create_or_resend_invitation,
    list_project_invitations,
    revoke_project_invitation,
)

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
    *,
    can_manage_secrets: bool,
    can_manage_runtime_tokens: bool,
    can_manage_team: bool,
    can_view_audit_logs: bool,
    stats_map: dict[uuid.UUID, dict[str, object]] | None = None,
) -> ProjectRead:
    stats = (stats_map or {}).get(project.id, {})
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        role=role,
        audit_log_visibility=project.audit_log_visibility,
        can_manage_secrets=can_manage_secrets,
        can_manage_runtime_tokens=can_manage_runtime_tokens,
        can_manage_team=can_manage_team,
        can_view_audit_logs=can_view_audit_logs,
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
        can_manage_runtime_tokens=member.can_manage_runtime_tokens,
        can_manage_team=member.can_manage_team,
        can_view_audit_logs=member.can_view_audit_logs,
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


def _get_user_by_email_or_404(db: Session, *, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{email}' not found.",
        )
    return user


def _build_member_revoke_context(
    db: Session,
    *,
    project: Project,
    email: str,
) -> dict[str, object]:
    revoked_user = _get_user_by_email_or_404(db, email=email)

    if revoked_user.id == project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project owner cannot be revoked.",
        )

    membership = _get_project_member_or_404(
        db,
        project_id=project.id,
        user_id=revoked_user.id,
    )
    shared_tokens = _get_shared_runtime_tokens_for_member(
        db,
        project_id=project.id,
        user_id=revoked_user.id,
    )
    revealed_shared_tokens = _get_revealed_runtime_tokens_for_member(
        db,
        project_id=project.id,
        user_id=revoked_user.id,
        shared_tokens=shared_tokens,
    )

    return {
        "user": revoked_user,
        "membership": membership,
        "shared_tokens": shared_tokens,
        "revealed_shared_tokens": revealed_shared_tokens,
    }


def _raise_shared_token_revoke_conflict(
    *,
    contexts: list[dict[str, object]],
    bulk: bool,
) -> None:
    conflict_members = [
        {
            "email": str(context["user"].email),
            "shared_tokens": [
                {"id": str(token.id), "name": token.name}
                for token in context["shared_tokens"]
            ],
            "revealed_shared_tokens": [
                {"id": str(token.id), "name": token.name}
                for token in context["revealed_shared_tokens"]
            ],
        }
        for context in contexts
        if context["shared_tokens"]
    ]
    if not conflict_members:
        return

    if bulk:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "shared_runtime_token_confirmation_required",
                "message": "One or more selected members have shared runtime tokens. Retry with shared_token_action set to 'keep_active' or 'revoke_tokens'.",
                "members": conflict_members,
            },
        )

    member_conflict = conflict_members[0]
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "shared_runtime_token_confirmation_required",
            "message": "This member has shared runtime tokens. Retry with shared_token_action set to 'keep_active' or 'revoke_tokens'.",
            "shared_token_count": len(member_conflict["shared_tokens"]),
            "shared_tokens": member_conflict["shared_tokens"],
            "revealed_shared_tokens": member_conflict["revealed_shared_tokens"],
        },
    )


def _apply_member_revoke(
    db: Session,
    *,
    project: Project,
    current_user: User,
    context: dict[str, object],
    shared_token_action: str | None,
) -> tuple[dict[str, object], str]:
    revoked_user = context["user"]
    membership = context["membership"]
    shared_tokens = context["shared_tokens"]
    revealed_shared_tokens = context["revealed_shared_tokens"]

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
    if shared_token_action == "revoke_tokens":
        for token in shared_tokens:
            revoked_token_count += 1
            write_audit_log(
                db,
                project_id=project.id,
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
    revoke_meta = {
        "email": revoked_user.email,
        "removed_shared_token_count": len(share_rows),
        "removed_shared_token_names": [token.name for token in shared_tokens],
        "revealed_shared_token_names": [token.name for token in revealed_shared_tokens],
        "shared_token_action": shared_token_action or "not_applicable",
        "revoked_runtime_token_count": revoked_token_count,
    }
    write_audit_log(
        db,
        project_id=project.id,
        user_id=current_user.id,
        action="member.revoked",
        metadata=revoke_meta,
    )

    detail = "Member access revoked."
    if share_rows:
        detail += f" Removed {len(share_rows)} runtime token share(s)."
    if revoked_token_count:
        detail += f" Revoked {revoked_token_count} underlying runtime token(s)."

    return revoke_meta, detail


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

    project = Project(
        name=project_name,
        description=description,
        owner_id=current_user.id,
        audit_log_visibility="owner_only",
    )
    db.add(project)
    db.flush()

    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=current_user.id,
            role=ROLE_OWNER,
            can_push_pull_secrets=True,
            can_manage_runtime_tokens=True,
            can_manage_team=True,
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
    return _serialize_project(
        project,
        ROLE_OWNER,
        can_manage_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
        stats_map=stats_map,
    )


@router.get("", response_model=list[ProjectRead])
def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectRead]:
    membership = aliased(ProjectMember)
    stmt = (
        select(
            Project,
            membership.role,
            membership.can_push_pull_secrets,
            membership.can_manage_runtime_tokens,
            membership.can_manage_team,
            membership.can_view_audit_logs,
        )
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
    stats_map = _get_project_stats_map(
        db,
        project_ids=[project.id for project, *_ in rows],
    )
    return [
        _serialize_project(
            project,
            ROLE_OWNER if project.owner_id == current_user.id else role or ROLE_MEMBER,
            can_manage_secrets=(
                True if project.owner_id == current_user.id else bool(can_push_pull_secrets)
            ),
            can_manage_runtime_tokens=(
                True if project.owner_id == current_user.id else bool(can_manage_runtime_tokens)
            ),
            can_manage_team=True if project.owner_id == current_user.id else bool(can_manage_team),
            can_view_audit_logs=(
                True
                if project.owner_id == current_user.id
                else (
                    project.audit_log_visibility == "members"
                    or (
                        project.audit_log_visibility == "specific"
                        and bool(can_view_audit_logs)
                    )
                )
            ),
            stats_map=stats_map,
        )
        for (
            project,
            role,
            can_push_pull_secrets,
            can_manage_runtime_tokens,
            can_manage_team,
            can_view_audit_logs,
        ) in rows
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
    return _serialize_project(
        project_access.project,
        project_access.role,
        can_manage_secrets=project_access.role == ROLE_OWNER or project_access.can_push_pull_secrets,
        can_manage_runtime_tokens=(
            project_access.role == ROLE_OWNER or project_access.can_manage_runtime_tokens
        ),
        can_manage_team=project_access.role == ROLE_OWNER or project_access.can_manage_team,
        can_view_audit_logs=project_access.role == ROLE_OWNER or project_access.can_view_audit_logs,
        stats_map=stats_map,
    )


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

    if payload.audit_log_visibility is not None:
        project_access.project.audit_log_visibility = payload.audit_log_visibility
        metadata["audit_log_visibility"] = payload.audit_log_visibility

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
    return _serialize_project(
        project_access.project,
        project_access.role,
        can_manage_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
        stats_map=stats_map,
    )


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


@router.patch("/{project_id}/environments/{environment_id}", response_model=EnvironmentRead)
def rename_environment(
    environment_id: uuid.UUID,
    payload: EnvironmentUpdate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Environment:
    environment = get_project_environment_or_404(db, project=project_access.project, environment_id=environment_id)

    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Environment name cannot be empty.",
        )

    if new_name == environment.name:
        return environment

    existing = db.scalar(
        select(Environment).where(
            Environment.project_id == project_access.project.id,
            Environment.name == new_name,
            Environment.id != environment_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An environment with that name already exists in this project.",
        )

    old_name = environment.name
    environment.name = new_name
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="environment.renamed",
        metadata={"old_name": old_name, "new_name": new_name},
    )
    db.commit()
    db.refresh(environment)
    return environment


@router.delete("/{project_id}/environments/{environment_id}", response_model=MessageResponse)
def delete_environment(
    environment_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    environment = get_project_environment_or_404(db, project=project_access.project, environment_id=environment_id)

    environment_name = environment.name
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=None,
        user_id=current_user.id,
        action="environment.deleted",
        metadata={"environment_name": environment_name},
    )
    db.delete(environment)
    db.commit()
    return MessageResponse(detail=f"Environment '{environment_name}' deleted.")


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
                can_manage_runtime_tokens=True,
                can_manage_team=True,
                can_view_audit_logs=True,
                joined_at=project_access.project.created_at,
            )

    return list(members.values())


@router.get(
    "/{project_id}/invitations",
    response_model=list[ProjectInvitationRead],
)
def list_pending_invitations(
    project_access: ProjectAccess = Depends(require_team_management),
    db: Session = Depends(get_db),
) -> list[ProjectInvitationRead]:
    return list_project_invitations(db, project=project_access.project)


@router.post(
    "/{project_id}/invitations/{invitation_id}/revoke",
    response_model=MessageResponse,
)
def revoke_invitation(
    invitation_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_team_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    revoke_project_invitation(
        db,
        project=project_access.project,
        invitation_id=invitation_id,
        revoked_by=current_user,
    )
    return MessageResponse(detail="Invitation revoked.")


@router.post(
    "/{project_id}/invite",
    response_model=InviteMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    payload: MemberInviteRequest,
    project_access: ProjectAccess = Depends(require_team_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteMemberResponse:
    return create_or_resend_invitation(
        db,
        project=project_access.project,
        invited_email=str(payload.email),
        role=payload.role,
        can_push_pull_secrets=payload.can_push_pull_secrets,
        can_manage_runtime_tokens=payload.can_manage_runtime_tokens,
        can_manage_team=payload.can_manage_team,
        can_view_audit_logs=payload.can_view_audit_logs,
        invited_by=current_user,
    )


def _apply_member_permission_updates(
    membership: ProjectMember,
    payload: MemberPermissionUpdateRequest | MemberBulkPermissionUpdateRequest,
) -> dict[str, bool]:
    updates: dict[str, bool] = {}
    if payload.can_push_pull_secrets is not None:
        membership.can_push_pull_secrets = payload.can_push_pull_secrets
        updates["can_push_pull_secrets"] = payload.can_push_pull_secrets
    if payload.can_manage_runtime_tokens is not None:
        membership.can_manage_runtime_tokens = payload.can_manage_runtime_tokens
        updates["can_manage_runtime_tokens"] = payload.can_manage_runtime_tokens
    if payload.can_manage_team is not None:
        membership.can_manage_team = payload.can_manage_team
        updates["can_manage_team"] = payload.can_manage_team
    if payload.can_view_audit_logs is not None:
        membership.can_view_audit_logs = payload.can_view_audit_logs
        updates["can_view_audit_logs"] = payload.can_view_audit_logs
    return updates


@router.post("/{project_id}/members/permissions", response_model=ProjectMemberRead)
def update_member_permissions(
    payload: MemberPermissionUpdateRequest,
    project_access: ProjectAccess = Depends(require_team_management),
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
            detail="Project owner permissions cannot be changed.",
        )

    membership = _get_project_member_or_404(
        db,
        project_id=project_access.project.id,
        user_id=member_user.id,
    )
    updates = _apply_member_permission_updates(membership, payload)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="member.permissions.updated",
        metadata={"email": member_user.email, **updates},
    )
    db.commit()
    db.refresh(membership)
    return _serialize_member(membership, member_user)


@router.post("/{project_id}/members/permissions/bulk", response_model=list[ProjectMemberRead])
def bulk_update_member_permissions(
    payload: MemberBulkPermissionUpdateRequest,
    project_access: ProjectAccess = Depends(require_team_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectMemberRead]:
    normalized_emails = [email.strip().lower() for email in payload.emails]
    users = db.scalars(select(User).where(User.email.in_(normalized_emails))).all()
    users_by_email = {user.email.lower(): user for user in users}
    updated_members: list[ProjectMemberRead] = []

    for email in normalized_emails:
        member_user = users_by_email.get(email)
        if member_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User not found: {email}",
            )
        if member_user.id == project_access.project.owner_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Project owner permissions cannot be changed.",
            )

        membership = _get_project_member_or_404(
            db,
            project_id=project_access.project.id,
            user_id=member_user.id,
        )
        _apply_member_permission_updates(membership, payload)
        updated_members.append(_serialize_member(membership, member_user))

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="members.permissions.bulk_updated",
        metadata={
            "emails": normalized_emails,
            "can_push_pull_secrets": payload.can_push_pull_secrets,
            "can_manage_runtime_tokens": payload.can_manage_runtime_tokens,
            "can_manage_team": payload.can_manage_team,
        },
    )
    db.commit()
    return updated_members


@router.post("/{project_id}/revoke", response_model=MessageResponse)
def revoke_member(
    payload: MemberRevokeRequest,
    project_access: ProjectAccess = Depends(require_team_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    revoked_email = payload.email.strip().lower()
    context = _build_member_revoke_context(
        db,
        project=project_access.project,
        email=revoked_email,
    )
    if payload.shared_token_action is None:
        _raise_shared_token_revoke_conflict(contexts=[context], bulk=False)
    revoke_meta, detail = _apply_member_revoke(
        db,
        project=project_access.project,
        current_user=current_user,
        context=context,
        shared_token_action=payload.shared_token_action,
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="member.revoked")
    db.commit()
    dispatch_webhooks(webhook_targets, event="member.revoked", project_id=project_access.project.id, environment_id=None, actor_user_id=current_user.id, metadata=revoke_meta)
    return MessageResponse(detail=detail)


@router.post("/{project_id}/members/bulk-revoke", response_model=MessageResponse)
def bulk_revoke_members(
    payload: MemberBulkRevokeRequest,
    project_access: ProjectAccess = Depends(require_team_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    normalized_emails: list[str] = []
    seen_emails: set[str] = set()
    for raw_email in payload.emails:
        email = str(raw_email).strip().lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        normalized_emails.append(email)

    contexts = [
        _build_member_revoke_context(
            db,
            project=project_access.project,
            email=email,
        )
        for email in normalized_emails
    ]
    if payload.shared_token_action is None:
        _raise_shared_token_revoke_conflict(contexts=contexts, bulk=True)

    revoke_metas: list[dict[str, object]] = []
    for context in contexts:
        revoke_meta, _detail = _apply_member_revoke(
            db,
            project=project_access.project,
            current_user=current_user,
            context=context,
            shared_token_action=payload.shared_token_action,
        )
        revoke_metas.append(revoke_meta)

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="members.bulk_revoked",
        metadata={
            "count": len(revoke_metas),
            "emails": [str(meta["email"]) for meta in revoke_metas],
            "shared_token_action": payload.shared_token_action or "not_applicable",
        },
    )
    webhook_targets = get_webhooks_for_event(
        db,
        project_id=project_access.project.id,
        action="member.revoked",
    )
    db.commit()

    for revoke_meta in revoke_metas:
        dispatch_webhooks(
            webhook_targets,
            event="member.revoked",
            project_id=project_access.project.id,
            environment_id=None,
            actor_user_id=current_user.id,
            metadata=revoke_meta,
        )

    return MessageResponse(detail=f"Revoked {len(revoke_metas)} member(s).")
