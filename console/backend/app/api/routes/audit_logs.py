from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import ProjectAccess, get_current_user, require_audit_log_access
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.cli_auth_audit_log import CliAuthAuditLog
from app.models.cli_auth_session import CliAuthSession
from app.models.environment import Environment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.audit_log import AuditLogRead, UnifiedAuditLogListResponse, UnifiedAuditLogRead
from app.services.audit import maybe_cleanup_old_audit_logs, write_audit_log

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


def _parse_cursor(cursor: str | None) -> datetime | None:
    if cursor is None:
        return None

    try:
        parsed = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid audit cursor.",
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


@router.get("/{project_id}/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    project_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    project_access: ProjectAccess = Depends(require_audit_log_access),
    current_user: User = Depends(get_current_user),
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

    response = [
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
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="audit_logs.viewed",
        metadata={"limit": limit},
    )
    db.commit()
    return response


@router.get("/{project_id}/audit-logs/export")
def export_audit_logs(
    project_id: uuid.UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    project_access: ProjectAccess = Depends(require_audit_log_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    actor = aliased(User)
    environment = aliased(Environment)

    rows = db.execute(
        select(AuditLog, actor.email, environment.name)
        .outerjoin(actor, actor.id == AuditLog.user_id)
        .outerjoin(environment, environment.id == AuditLog.environment_id)
        .where(AuditLog.project_id == project_access.project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(10_000)
    ).all()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"audit-logs-{project_id}-{timestamp}.{format}"
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="audit_logs.exported",
        metadata={"format": format},
    )
    db.commit()

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "created_at", "action", "actor_email", "environment_name", "environment_id", "user_id", "metadata"])
        for audit_log, actor_email, environment_name in rows:
            writer.writerow([
                str(audit_log.id),
                audit_log.created_at.isoformat(),
                audit_log.action,
                actor_email or "",
                environment_name or "",
                str(audit_log.environment_id) if audit_log.environment_id else "",
                str(audit_log.user_id) if audit_log.user_id else "",
                json.dumps(audit_log.metadata_json) if audit_log.metadata_json else "",
            ])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    records = [
        {
            "id": str(audit_log.id),
            "created_at": audit_log.created_at.isoformat(),
            "action": audit_log.action,
            "actor_email": actor_email,
            "environment_name": environment_name,
            "environment_id": str(audit_log.environment_id) if audit_log.environment_id else None,
            "user_id": str(audit_log.user_id) if audit_log.user_id else None,
            "metadata": audit_log.metadata_json,
        }
        for audit_log, actor_email, environment_name in rows
    ]
    return StreamingResponse(
        iter([json.dumps(records, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@unified_router.get("/unified", response_model=UnifiedAuditLogListResponse)
def list_unified_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    source: str = Query(default="all", pattern="^(all|project|cli_auth)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnifiedAuditLogListResponse:
    maybe_cleanup_old_audit_logs(db)
    cursor_dt = _parse_cursor(cursor)

    accessible_project_ids = db.scalars(
        select(Project.id)
        .outerjoin(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == current_user.id),
        )
        .where(
            or_(
                Project.owner_id == current_user.id,
                and_(
                    ProjectMember.user_id == current_user.id,
                    or_(
                        Project.audit_log_visibility == "members",
                        and_(
                            Project.audit_log_visibility == "specific",
                            ProjectMember.can_view_audit_logs.is_(True),
                        ),
                    ),
                ),
            )
        )
    ).all()
    project_ids = list(accessible_project_ids)

    if project_id is not None:
        if project_id not in project_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this project.",
            )
        project_ids = [project_id]

    actor = aliased(User)
    environment = aliased(Environment)
    cli_actor = aliased(User)
    fetch_limit = limit + 1
    project_rows = []
    if project_ids and source in {"all", "project"}:
        project_stmt = (
            select(AuditLog, actor.email, environment.name)
            .outerjoin(actor, actor.id == AuditLog.user_id)
            .outerjoin(environment, environment.id == AuditLog.environment_id)
            .where(AuditLog.project_id.in_(project_ids))
            .order_by(AuditLog.created_at.desc())
            .limit(fetch_limit)
        )
        if cursor_dt is not None:
            project_stmt = project_stmt.where(AuditLog.created_at < cursor_dt)

        project_rows = db.execute(project_stmt).all()

    cli_rows = []
    if source in {"all", "cli_auth"}:
        cli_stmt = (
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
            .limit(fetch_limit)
        )
        if cursor_dt is not None:
            cli_stmt = cli_stmt.where(CliAuthAuditLog.created_at < cursor_dt)

        cli_rows = db.execute(cli_stmt).all()

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
    has_more = len(merged_entries) > limit
    visible_entries = merged_entries[:limit]
    next_cursor = visible_entries[-1].created_at.astimezone(timezone.utc).isoformat() if has_more and visible_entries else None
    return UnifiedAuditLogListResponse(logs=visible_entries, next_cursor=next_cursor)
