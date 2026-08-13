from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.environment import Environment
from app.models.project import Project
from app.models.secret import Secret
from app.services.secret_structure import normalize_secret_path, path_is_within


def archive_old_secret_versions(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str,
    key: str,
) -> list[int]:
    project = db.get(Project, project_id)
    if project is None:
        return []
    rows = list(
        db.scalars(
            select(Secret)
            .where(
                Secret.environment_id == environment_id,
                Secret.path == path,
                Secret.key == key,
                Secret.archived_at.is_(None),
            )
            .order_by(Secret.version.desc())
        ).all()
    )
    if len(rows) <= 1:
        return []

    now = datetime.now(timezone.utc)
    version_limit = max(1, project.secret_retention_versions)
    retention_cutoff = (
        now - timedelta(days=project.secret_retention_days)
        if project.secret_retention_days is not None
        else None
    )
    deleted_cutoff = (
        now - timedelta(days=project.secret_archive_deleted_after_days)
        if project.secret_archive_deleted_after_days is not None
        else None
    )
    archived: list[int] = []
    for index, row in enumerate(rows):
        if index == 0:
            continue
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        should_archive = index >= version_limit
        should_archive = should_archive or (
            retention_cutoff is not None and updated_at < retention_cutoff
        )
        should_archive = should_archive or (
            deleted_cutoff is not None and row.is_deleted and updated_at < deleted_cutoff
        )
        if should_archive:
            row.archived_at = now
            archived.append(row.version)
    return archived


def get_secret_versions(
    db: Session,
    *,
    environment_id: uuid.UUID,
    path: str,
    key: str,
    include_archived: bool = True,
) -> list[Secret]:
    stmt = select(Secret).where(
        Secret.environment_id == environment_id,
        Secret.path == normalize_secret_path(path),
        Secret.key == key,
    )
    if not include_archived:
        stmt = stmt.where(Secret.archived_at.is_(None))
    return list(db.scalars(stmt.order_by(Secret.version.desc())).all())


def get_environment_snapshot(
    db: Session,
    *,
    environment_id: uuid.UUID,
    at: datetime,
    path: str = "/",
    recursive: bool = False,
) -> list[Secret]:
    selected_path = normalize_secret_path(path)
    timestamp = at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)
    latest_versions = (
        select(
            Secret.path.label("path"),
            Secret.key.label("key"),
            func.max(Secret.version).label("version"),
        )
        .where(Secret.environment_id == environment_id, Secret.updated_at <= timestamp)
        .group_by(Secret.path, Secret.key)
        .subquery()
    )
    rows = list(
        db.scalars(
            select(Secret)
            .join(
                latest_versions,
                (Secret.path == latest_versions.c.path)
                & (Secret.key == latest_versions.c.key)
                & (Secret.version == latest_versions.c.version),
            )
            .where(Secret.environment_id == environment_id)
            .order_by(Secret.path.asc(), Secret.key.asc())
        ).all()
    )
    return [
        row
        for row in rows
        if (path_is_within(row.path, selected_path) if recursive else row.path == selected_path)
    ]


def get_project_environments(db: Session, *, project_id: uuid.UUID) -> list[Environment]:
    return list(
        db.scalars(
            select(Environment)
            .where(Environment.project_id == project_id)
            .order_by(Environment.created_at.asc())
        ).all()
    )
