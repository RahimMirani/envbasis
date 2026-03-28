from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import ProjectAccess, get_current_user, require_project_owner
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.cli_auth_audit_log import CliAuthAuditLog
from app.models.cli_auth_session import CliAuthSession
from app.models.environment import Environment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.audit_log import AuditLogRead, UnifiedAuditLogRead
from app.services.audit import maybe_cleanup_old_audit_logs

router = APIRouter(prefix="/projects")
unified_router = APIRouter(prefix="/audit-logs")

CLI_AUTH_SENSITIVE_METADATA_KEYS = {
    "access_token",
    "code",
    "device_code",
    "refresh_token",
    "user_code",
}


def _sanitize_cli_auth_metadata(metadata: dict | None) -> dict | None:
    if not metadata:
        return metadata

    sanitized_metadata = {
        key: value for key, value in metadata.items() if key not in CLI_AUTH_SENSITIVE_METADATA_KEYS
    }
    return sanitized_metadata or None


@router.get("/{project_id}/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    project_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    maybe_cleanup_old_audit_logs(db)
    actor = aliased(User)
    environment = aliased(Environment)

    rows = db.execute(
        select(AuditLog, actor.email, environment.name)
        .outerjoin(actor, actor.id == AuditLog.user_id)
        .outerjoin(environment, environment.id == AuditLog.environment_id)
        .where(AuditLog.project_id == project_access.project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()

    return [
        AuditLogRead(
            id=audit_log.id,
            project_id=audit_log.project_id,
            environment_id=audit_log.environment_id,
            environment_name=environment_name,
            user_id=audit_log.user_id,
            actor_email=actor_email,
            action=audit_log.action,
            metadata_json=audit_log.metadata_json,
            created_at=audit_log.created_at,
        )
        for audit_log, actor_email, environment_name in rows
    ]


@unified_router.get("/unified", response_model=list[UnifiedAuditLogRead])
def list_unified_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UnifiedAuditLogRead]:
    maybe_cleanup_old_audit_logs(db)

    accessible_project_ids = db.scalars(
        select(Project.id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == current_user.id),
        )
        .where(or_(Project.owner_id == current_user.id, ProjectMember.user_id == current_user.id))
    ).all()
    project_ids = list(accessible_project_ids)

    actor = aliased(User)
    environment = aliased(Environment)
    cli_actor = aliased(User)
    project_rows = []
    if project_ids:
        project_rows = db.execute(
            select(AuditLog, actor.email, environment.name)
            .outerjoin(actor, actor.id == AuditLog.user_id)
            .outerjoin(environment, environment.id == AuditLog.environment_id)
            .where(AuditLog.project_id.in_(project_ids))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        ).all()

    cli_rows = db.execute(
        select(CliAuthAuditLog, cli_actor.email)
        .outerjoin(cli_actor, cli_actor.id == CliAuthAuditLog.user_id)
        .outerjoin(CliAuthSession, CliAuthSession.id == CliAuthAuditLog.cli_auth_session_id)
        .where(
            or_(
                CliAuthAuditLog.user_id == current_user.id,
                CliAuthSession.approved_by_user_id == current_user.id,
            )
        )
        .order_by(CliAuthAuditLog.created_at.desc())
        .limit(limit)
    ).all()

    merged_entries: list[UnifiedAuditLogRead] = [
        UnifiedAuditLogRead(
            id=audit_log.id,
            source="project",
            project_id=audit_log.project_id,
            environment_id=audit_log.environment_id,
            environment_name=environment_name,
            cli_auth_session_id=None,
            user_id=audit_log.user_id,
            actor_email=actor_email,
            action=audit_log.action,
            metadata_json=audit_log.metadata_json,
            created_at=audit_log.created_at,
        )
        for audit_log, actor_email, environment_name in project_rows
    ]
    merged_entries.extend(
        [
            UnifiedAuditLogRead(
                id=cli_audit_log.id,
                source="cli_auth",
                project_id=None,
                environment_id=None,
                environment_name=None,
                cli_auth_session_id=cli_audit_log.cli_auth_session_id,
                user_id=cli_audit_log.user_id,
                actor_email=actor_email,
                action=cli_audit_log.action,
                metadata_json=_sanitize_cli_auth_metadata(cli_audit_log.metadata_json),
                created_at=cli_audit_log.created_at,
            )
            for cli_audit_log, actor_email in cli_rows
        ]
    )
    merged_entries.sort(key=lambda item: item.created_at, reverse=True)
    return merged_entries[:limit]
