from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    ProjectAccess,
    enforce_project_permission,
    enforce_machine_secret_key,
    get_current_user,
    get_project_access,
    require_project_owner,
    require_secret_management,
)
from app.api.routes.secrets import _create_secret_version, _validate_secret_key
from app.db.session import get_db
from app.models.secret import Secret
from app.models.project import Project
from app.models.user import User
from app.schemas.secret_history import (
    RecoveryItem,
    RecoveryRequest,
    RecoveryResponse,
    SecretHistoricalRevealResponse,
    SecretRetentionRead,
    SecretRetentionUpdate,
    SecretRollbackResponse,
    SecretVersionItem,
    SecretVersionListResponse,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.project_encryption import decrypt_project_secret
from app.services.secret_history import (
    get_environment_snapshot,
    get_project_environments,
    get_secret_versions,
)
from app.services.secret_structure import normalize_secret_path, path_is_within
from app.services.secrets import get_latest_secret_rows

router = APIRouter(prefix="/projects")


def _users_by_id(db: Session, rows: list[Secret]) -> dict[uuid.UUID, User]:
    ids = {row.updated_by for row in rows if row.updated_by is not None}
    if not ids:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(ids))).all()}


def _version_item(row: Secret, users: dict[uuid.UUID, User]) -> SecretVersionItem:
    return SecretVersionItem(
        key=row.key,
        path=row.path,
        version=row.version,
        is_deleted=row.is_deleted,
        is_reference=row.is_reference,
        tags=row.tags,
        description=row.description,
        owner=row.owner,
        service=row.service,
        rotation_interval_days=row.rotation_interval_days,
        rotate_at=row.rotate_at,
        expires_at=row.expires_at,
        custom_metadata=row.custom_metadata,
        updated_by_user_id=row.updated_by,
        updated_by_email=users.get(row.updated_by).email if row.updated_by in users else None,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _historical_row_or_404(
    db: Session,
    *,
    environment_id: uuid.UUID,
    path: str,
    key: str,
    version: int,
) -> Secret:
    row = db.scalar(
        select(Secret).where(
            Secret.environment_id == environment_id,
            Secret.path == path,
            Secret.key == key,
            Secret.version == version,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Secret version not found.")
    return row


@router.get(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}/versions",
    response_model=SecretVersionListResponse,
)
def list_secret_versions(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    path: Annotated[str, Query(max_length=512)] = "/",
    include_archived: bool = True,
    project_access: ProjectAccess = Depends(get_project_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretVersionListResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    selected_path = normalize_secret_path(path)
    enforce_project_permission(db, project_access=project_access, resource="secrets", action="list", environment_id=environment.id, path=selected_path, legacy_allowed=True)
    key = _validate_secret_key(secret_key)
    enforce_machine_secret_key(project_access, key)
    rows = get_secret_versions(
        db,
        environment_id=environment.id,
        path=selected_path,
        key=key,
        include_archived=include_archived,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Secret not found.")
    users = _users_by_id(db, rows)
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_versions.listed",
        metadata={"key": key, "path": selected_path, "include_archived": include_archived},
    )
    db.commit()
    return SecretVersionListResponse(
        project_id=project_id,
        environment_id=environment.id,
        key=key,
        path=selected_path,
        versions=[_version_item(row, users) for row in rows],
    )


@router.get(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}/versions/{version}/reveal",
    response_model=SecretHistoricalRevealResponse,
)
def reveal_secret_version(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    version: int,
    path: Annotated[str, Query(max_length=512)] = "/",
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretHistoricalRevealResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    selected_path = normalize_secret_path(path)
    enforce_project_permission(db, project_access=project_access, resource="secrets", action="read", environment_id=environment.id, path=selected_path, legacy_allowed=project_access.can_push_pull_secrets)
    key = _validate_secret_key(secret_key)
    enforce_machine_secret_key(project_access, key)
    row = _historical_row_or_404(
        db,
        environment_id=environment.id,
        path=selected_path,
        key=key,
        version=version,
    )
    if row.is_deleted:
        raise HTTPException(status_code=409, detail="Deleted versions have no revealable value.")
    users = _users_by_id(db, [row])
    value = decrypt_project_secret(
        db,
        project_id=project_id,
        encrypted_value=row.encrypted_value,
        encryption_key_version=row.encryption_key_version,
    )
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_version.revealed",
        metadata={"key": key, "path": selected_path, "version": version},
    )
    db.commit()
    item = _version_item(row, users)
    return SecretHistoricalRevealResponse(
        **item.model_dump(),
        project_id=project_id,
        environment_id=environment.id,
        value=value,
        revealed_at=datetime.now(timezone.utc),
    )


@router.post(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}/versions/{version}/rollback",
    response_model=SecretRollbackResponse,
)
def rollback_secret_version(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    version: int,
    path: Annotated[str, Query(max_length=512)] = "/",
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretRollbackResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    selected_path = normalize_secret_path(path)
    enforce_project_permission(db, project_access=project_access, resource="secrets", action="write", environment_id=environment.id, path=selected_path, legacy_allowed=project_access.can_push_pull_secrets)
    key = _validate_secret_key(secret_key)
    enforce_machine_secret_key(project_access, key)
    source = _historical_row_or_404(
        db, environment_id=environment.id, path=selected_path, key=key, version=version
    )
    if source.is_deleted:
        raise HTTPException(status_code=409, detail="A deleted version cannot be rolled back as a value.")
    versions = get_secret_versions(
        db, environment_id=environment.id, path=selected_path, key=key
    )
    latest = versions[0]
    value = decrypt_project_secret(
        db,
        project_id=project_id,
        encrypted_value=source.encrypted_value,
        encryption_key_version=source.encryption_key_version,
    )
    restored = _create_secret_version(
        db=db,
        project_id=project_id,
        environment_id=environment.id,
        key=key,
        value=value,
        version=latest.version + 1,
        updated_by=current_user.id,
        expires_at=source.expires_at,
        path=source.path,
        tags=source.tags,
        description=source.description,
        owner=source.owner,
        service=source.service,
        rotation_interval_days=source.rotation_interval_days,
        rotate_at=source.rotate_at,
        custom_metadata=source.custom_metadata,
        is_reference=source.is_reference,
    )
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_version.rolled_back",
        metadata={
            "key": key,
            "path": selected_path,
            "source_version": source.version,
            "version": restored.version,
        },
    )
    db.commit()
    db.refresh(restored)
    return SecretRollbackResponse(
        project_id=project_id,
        environment_id=environment.id,
        key=key,
        path=selected_path,
        source_version=source.version,
        version=restored.version,
        updated_at=restored.updated_at,
    )


def _recover_environment(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: RecoveryRequest,
    current_user: User,
) -> list[RecoveryItem]:
    snapshot_rows = get_environment_snapshot(
        db,
        environment_id=environment_id,
        at=payload.at,
        path=payload.path,
        recursive=payload.recursive,
    )
    current_rows = [
        row
        for row in get_latest_secret_rows(db, environment_id=environment_id, include_deleted=True)
        if (path_is_within(row.path, payload.path) if payload.recursive else row.path == payload.path)
    ]
    snapshot = {(row.path, row.key): row for row in snapshot_rows}
    current = {(row.path, row.key): row for row in current_rows}
    changes: list[RecoveryItem] = []

    for location in sorted(set(snapshot) | set(current)):
        historical = snapshot.get(location)
        latest = current.get(location)
        if historical is not None and not historical.is_deleted:
            action = "restore" if latest is None or latest.version != historical.version else "unchanged"
        elif latest is not None and not latest.is_deleted:
            action = "delete"
        else:
            action = "unchanged"
        if action == "unchanged":
            continue
        item = RecoveryItem(
            key=location[1],
            path=location[0],
            snapshot_version=historical.version if historical is not None else None,
            current_version=latest.version if latest is not None else None,
            action=action,
        )
        changes.append(item)
        if payload.dry_run:
            continue
        next_version = (latest.version if latest is not None else historical.version) + 1
        if action == "restore" and historical is not None:
            value = decrypt_project_secret(
                db,
                project_id=project_id,
                encrypted_value=historical.encrypted_value,
                encryption_key_version=historical.encryption_key_version,
            )
            _create_secret_version(
                db=db,
                project_id=project_id,
                environment_id=environment_id,
                key=historical.key,
                value=value,
                version=next_version,
                updated_by=current_user.id,
                expires_at=historical.expires_at,
                path=historical.path,
                tags=historical.tags,
                description=historical.description,
                owner=historical.owner,
                service=historical.service,
                rotation_interval_days=historical.rotation_interval_days,
                rotate_at=historical.rotate_at,
                custom_metadata=historical.custom_metadata,
                is_reference=historical.is_reference,
            )
        elif latest is not None:
            _create_secret_version(
                db=db,
                project_id=project_id,
                environment_id=environment_id,
                key=latest.key,
                value="",
                version=next_version,
                updated_by=current_user.id,
                is_deleted=True,
                path=latest.path,
                tags=latest.tags,
                description=latest.description,
                owner=latest.owner,
                service=latest.service,
                rotation_interval_days=latest.rotation_interval_days,
                rotate_at=latest.rotate_at,
                custom_metadata=latest.custom_metadata,
                is_reference=latest.is_reference,
            )
    return changes


@router.post(
    "/{project_id}/environments/{environment_id}/secrets/recovery",
    response_model=RecoveryResponse,
)
def recover_environment_secrets(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: RecoveryRequest,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    enforce_project_permission(db, project_access=project_access, resource="secrets", action="write", environment_id=environment.id, path=payload.path, legacy_allowed=project_access.can_push_pull_secrets)
    changes = _recover_environment(
        db,
        project_id=project_id,
        environment_id=environment.id,
        payload=payload,
        current_user=current_user,
    )
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.recovery_previewed" if payload.dry_run else "secrets.recovered",
        metadata={"at": payload.at.isoformat(), "path": payload.path, "recursive": payload.recursive, "changed": len(changes)},
    )
    db.commit()
    return RecoveryResponse(
        project_id=project_id,
        environment_id=environment.id,
        at=payload.at,
        dry_run=payload.dry_run,
        changed=len(changes),
        environments_changed=1 if changes else 0,
        items=changes,
    )


@router.post("/{project_id}/secrets/recovery", response_model=RecoveryResponse)
def recover_project_secrets(
    project_id: uuid.UUID,
    payload: RecoveryRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecoveryResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    all_changes: list[RecoveryItem] = []
    changed_environments = 0
    for environment in get_project_environments(db, project_id=project_id):
        changes = _recover_environment(
            db,
            project_id=project_id,
            environment_id=environment.id,
            payload=payload,
            current_user=current_user,
        )
        if changes:
            changed_environments += 1
            all_changes.extend(changes)
    write_audit_log(
        db,
        project_id=project_id,
        user_id=current_user.id,
        action="project_secrets.recovery_previewed" if payload.dry_run else "project_secrets.recovered",
        metadata={"at": payload.at.isoformat(), "path": payload.path, "recursive": payload.recursive, "changed": len(all_changes), "environments_changed": changed_environments},
    )
    db.commit()
    return RecoveryResponse(
        project_id=project_id,
        at=payload.at,
        dry_run=payload.dry_run,
        changed=len(all_changes),
        environments_changed=changed_environments,
        items=all_changes,
    )


@router.get("/{project_id}/secret-retention", response_model=SecretRetentionRead)
def get_secret_retention(
    project_id: uuid.UUID,
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> SecretRetentionRead:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return SecretRetentionRead(
        project_id=project.id,
        retain_versions=project.secret_retention_versions,
        retain_days=project.secret_retention_days,
        archive_deleted_after_days=project.secret_archive_deleted_after_days,
    )


@router.patch("/{project_id}/secret-retention", response_model=SecretRetentionRead)
def update_secret_retention(
    project_id: uuid.UUID,
    payload: SecretRetentionUpdate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretRetentionRead:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    project.secret_retention_versions = payload.retain_versions
    project.secret_retention_days = payload.retain_days
    project.secret_archive_deleted_after_days = payload.archive_deleted_after_days
    write_audit_log(
        db,
        project_id=project_id,
        user_id=current_user.id,
        action="secret_retention.updated",
        metadata=payload.model_dump(),
    )
    db.commit()
    return SecretRetentionRead(project_id=project.id, **payload.model_dump())
