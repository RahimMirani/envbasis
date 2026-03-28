from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.cli_auth_audit_log import CliAuthAuditLog

_cleanup_lock = Lock()
_last_cleanup_at: datetime | None = None


def cleanup_old_audit_logs(db: Session, *, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    project_result = db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    cli_result = db.execute(delete(CliAuthAuditLog).where(CliAuthAuditLog.created_at < cutoff))
    return (project_result.rowcount or 0) + (cli_result.rowcount or 0)


def maybe_cleanup_old_audit_logs(db: Session) -> int:
    global _last_cleanup_at

    if settings.audit_log_retention_days <= 0:
        return 0

    now = datetime.now(timezone.utc)
    with _cleanup_lock:
        if (
            _last_cleanup_at is not None
            and (now - _last_cleanup_at).total_seconds() < settings.audit_log_cleanup_interval_seconds
        ):
            return 0

        deleted_count = cleanup_old_audit_logs(db, retention_days=settings.audit_log_retention_days)
        _last_cleanup_at = now
        return deleted_count


def write_audit_log(
    db: Session,
    *,
    project_id: uuid.UUID,
    action: str,
    user_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    maybe_cleanup_old_audit_logs(db)
    db.add(
        AuditLog(
            project_id=project_id,
            environment_id=environment_id,
            user_id=user_id,
            action=action,
            metadata_json=metadata,
        )
    )


def write_cli_auth_audit_log(
    db: Session,
    *,
    action: str,
    cli_auth_session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    maybe_cleanup_old_audit_logs(db)
    db.add(
        CliAuthAuditLog(
            cli_auth_session_id=cli_auth_session_id,
            user_id=user_id,
            action=action,
            metadata_json=metadata,
        )
    )
