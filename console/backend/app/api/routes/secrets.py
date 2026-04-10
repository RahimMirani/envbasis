from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, get_project_access, require_secret_access
from app.db.session import get_db
from app.models.environment import Environment
from app.models.secret import Secret
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.secret import (
    SecretBulkDeleteRequest,
    SecretCreateRequest,
    SecretDeleteResponse,
    EnvironmentSecretStatsRead,
    ProjectSecretItemRead,
    ProjectSecretListResponse,
    SecretItemRead,
    SecretListResponse,
    SecretMutationResponse,
    SecretRevealResponse,
    SecretPullResponse,
    ProjectSecretStatsResponse,
    SecretPushRequest,
    SecretPushResponse,
    SecretUpdateRequest,
    SecretVersionRead,
)
from app.services.audit import write_audit_log
from app.services.crypto import decrypt_secret_value, encrypt_secret_value
from app.services.environments import get_project_environment_or_404
from app.services.webhooks import dispatch_webhooks, get_webhooks_for_event
from app.services.secrets import (
    MAX_SECRET_KEY_LENGTH,
    build_secret_payload,
    get_latest_secret_rows,
    get_latest_project_secret_rows,
    get_project_secret_stats,
    validate_single_secret,
)

router = APIRouter(prefix="/projects")


def _validate_secret_key(key: str) -> str:
    normalized = key.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Secret keys cannot be empty.",
        )
    if len(normalized) > MAX_SECRET_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Secret key is too long. Maximum length is {MAX_SECRET_KEY_LENGTH}.",
        )
    return normalized


def _validate_secret_value(*, key: str, value: str) -> None:
    try:
        validate_single_secret(key=key, value=value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _validate_secret_expiration(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    else:
        expires_at = expires_at.astimezone(timezone.utc)

    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Secret expiration must be in the future.",
        )

    return expires_at


def _serialize_secret_expiration(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None

    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc)

    return expires_at.astimezone(timezone.utc)


def _create_secret_version(
    *,
    db: Session,
    environment_id: uuid.UUID,
    key: str,
    value: str,
    version: int,
    updated_by: uuid.UUID,
    expires_at: datetime | None = None,
    is_deleted: bool = False,
) -> Secret:
    secret = Secret(
        environment_id=environment_id,
        key=key,
        encrypted_value=encrypt_secret_value("" if is_deleted else value),
        version=version,
        is_deleted=is_deleted,
        updated_by=updated_by,
        expires_at=expires_at,
    )
    db.add(secret)
    db.flush()
    return secret


def _get_latest_secret_map(
    db: Session,
    *,
    environment_id: uuid.UUID,
) -> dict[str, Secret]:
    return {
        secret.key: secret
        for secret in get_latest_secret_rows(
            db,
            environment_id=environment_id,
            include_deleted=True,
        )
    }


def _get_users_by_id(db: Session, rows: list[Secret]) -> dict[uuid.UUID, User]:
    updated_by_ids = {row.updated_by for row in rows if row.updated_by is not None}
    if not updated_by_ids:
        return {}

    return {
        user.id: user
        for user in db.query(User).filter(User.id.in_(updated_by_ids)).all()
    }


@router.post(
    "/{project_id}/environments/{environment_id}/secrets/push",
    response_model=SecretPushResponse,
)
def push_secrets(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: SecretPushRequest,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretPushResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )

    latest_by_key = _get_latest_secret_map(db, environment_id=environment.id)
    versions: list[SecretVersionRead] = []
    changed = 0
    unchanged = 0
    changed_keys: list[str] = []

    for raw_key, raw_value in payload.secrets.items():
        key = _validate_secret_key(raw_key)
        value = raw_value
        latest = latest_by_key.get(key)

        if latest is not None and not latest.is_deleted and decrypt_secret_value(latest.encrypted_value) == value:
            unchanged += 1
            versions.append(
                SecretVersionRead(
                    key=key,
                    version=latest.version,
                    updated_at=latest.updated_at,
                )
            )
            continue

        version = 1 if latest is None else latest.version + 1
        secret = _create_secret_version(
            db=db,
            environment_id=environment.id,
            key=key,
            value=value,
            version=version,
            updated_by=current_user.id,
        )
        latest_by_key[key] = secret
        changed += 1
        changed_keys.append(key)
        versions.append(
            SecretVersionRead(
                key=key,
                version=secret.version,
                updated_at=secret.updated_at,
            )
        )

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.pushed",
        metadata={"changed_keys": changed_keys, "changed_count": changed, "unchanged_count": unchanged},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secrets.pushed")
    db.commit()
    dispatch_webhooks(webhook_targets, event="secrets.pushed", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"changed_keys": changed_keys, "changed_count": changed, "unchanged_count": unchanged})
    return SecretPushResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        total_received=len(payload.secrets),
        changed=changed,
        unchanged=unchanged,
        versions=versions,
    )


@router.get(
    "/{project_id}/secrets/stats",
    response_model=ProjectSecretStatsResponse,
)
def get_secret_stats(
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> ProjectSecretStatsResponse:
    environment_stats = get_project_secret_stats(db, project_id=project_access.project.id)
    return ProjectSecretStatsResponse(
        project_id=project_access.project.id,
        total_secret_count=sum(int(item["secret_count"]) for item in environment_stats),
        environments=[
            EnvironmentSecretStatsRead(**item)
            for item in environment_stats
        ],
        generated_at=datetime.now(timezone.utc),
    )


@router.get(
    "/{project_id}/secrets",
    response_model=ProjectSecretListResponse,
)
def list_project_secrets(
    project_id: uuid.UUID,
    key: Annotated[
        str | None,
        Query(
            max_length=128,
            description="Filter secrets by key (case-insensitive substring match)",
        ),
    ] = None,
    environment_id: Annotated[
        list[uuid.UUID] | None,
        Query(
            description="Optional environment scope. Repeat the parameter to include multiple environments.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Maximum number of secrets to return."),
    ] = 50,
    cursor: Annotated[
        str | None,
        Query(description="Offset cursor returned by a previous project secrets listing."),
    ] = None,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectSecretListResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    try:
        offset = int(cursor) if cursor else 0
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid cursor.",
        ) from exc

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid cursor.",
        )

    rows, next_cursor = get_latest_project_secret_rows(
        db,
        project_id=project_access.project.id,
        environment_ids=environment_id,
        key_filter=key,
        limit=limit,
        offset=offset,
    )
    secrets = [row for row, _environment in rows]
    users_by_id = _get_users_by_id(db, secrets)

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="secrets.listed",
        metadata={
            "secret_count": len(rows),
            "environment_scope": [str(value) for value in environment_id or []],
            "key_filter": key,
            "limit": limit,
            "cursor": cursor,
        },
    )
    db.commit()

    return ProjectSecretListResponse(
        project_id=project_access.project.id,
        secrets=[
            ProjectSecretItemRead(
                key=secret.key,
                version=secret.version,
                updated_at=secret.updated_at,
                expires_at=_serialize_secret_expiration(secret.expires_at),
                updated_by_user_id=secret.updated_by,
                updated_by_email=users_by_id.get(secret.updated_by).email if secret.updated_by in users_by_id else None,
                environment_id=environment.id,
                environment_name=environment.name,
            )
            for secret, environment in rows
        ],
        next_cursor=next_cursor,
        generated_at=datetime.now(timezone.utc),
    )


@router.get(
    "/{project_id}/environments/{environment_id}/secrets",
    response_model=SecretListResponse,
)
def list_secrets(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    key: Annotated[
        str | None,
        Query(
            max_length=128,
            description="Filter secrets by key (case-insensitive substring match)",
        ),
    ] = None,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretListResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )

    latest_rows = get_latest_secret_rows(db, environment_id=environment.id, key_filter=key)
    users_by_id = _get_users_by_id(db, latest_rows)

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.listed",
        metadata={"secret_count": len(latest_rows)},
    )
    db.commit()

    return SecretListResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        secrets=[
            SecretItemRead(
                key=row.key,
                version=row.version,
                updated_at=row.updated_at,
                expires_at=_serialize_secret_expiration(row.expires_at),
                updated_by_user_id=row.updated_by,
                updated_by_email=users_by_id.get(row.updated_by).email if row.updated_by in users_by_id else None,
            )
            for row in latest_rows
        ],
        generated_at=datetime.now(timezone.utc),
    )


@router.get(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}/reveal",
    response_model=SecretRevealResponse,
)
def reveal_secret(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretRevealResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    key = _validate_secret_key(secret_key)
    latest = _get_latest_secret_map(db, environment_id=environment.id).get(key)
    if latest is None or latest.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found.")

    users_by_id = _get_users_by_id(db, [latest])
    value = decrypt_secret_value(latest.encrypted_value)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.revealed",
        metadata={"secret_key": key, "version": latest.version},
    )
    db.commit()

    return SecretRevealResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        value=value,
        version=latest.version,
        updated_at=latest.updated_at,
        expires_at=_serialize_secret_expiration(latest.expires_at),
        updated_by_user_id=latest.updated_by,
        updated_by_email=users_by_id.get(latest.updated_by).email if latest.updated_by in users_by_id else None,
        revealed_at=datetime.now(timezone.utc),
    )


@router.get(
    "/{project_id}/environments/{environment_id}/secrets/pull",
    response_model=SecretPullResponse,
)
def pull_secrets(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretPullResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )

    latest_rows = get_latest_secret_rows(db, environment_id=environment.id)
    try:
        secrets, versions = build_secret_payload(latest_rows)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.pulled",
        metadata={"secret_count": len(secrets)},
    )
    db.commit()

    return SecretPullResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        secrets=secrets,
        versions=versions,
        generated_at=datetime.now(timezone.utc),
    )


@router.post(
    "/{project_id}/environments/{environment_id}/secrets",
    response_model=SecretMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_secret(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: SecretCreateRequest,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretMutationResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    key = _validate_secret_key(payload.key)
    _validate_secret_value(key=key, value=payload.value)
    expires_at = _validate_secret_expiration(payload.expires_at)

    latest_by_key = _get_latest_secret_map(db, environment_id=environment.id)
    latest = latest_by_key.get(key)
    if latest is not None and not latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Secret already exists. Use the update endpoint instead.",
        )

    version = 1 if latest is None else latest.version + 1
    secret = _create_secret_version(
        db=db,
        environment_id=environment.id,
        key=key,
        value=payload.value,
        version=version,
        updated_by=current_user.id,
        expires_at=expires_at,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.created",
        metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.created")
    db.commit()
    db.refresh(secret)
    dispatch_webhooks(webhook_targets, event="secret.created", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None})
    return SecretMutationResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        version=secret.version,
        updated_at=secret.updated_at,
        expires_at=_serialize_secret_expiration(secret.expires_at),
        changed=True,
    )


@router.patch(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}",
    response_model=SecretMutationResponse,
)
def update_secret(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    payload: SecretUpdateRequest,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretMutationResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    key = _validate_secret_key(secret_key)
    _validate_secret_value(key=key, value=payload.value)
    expires_at = _validate_secret_expiration(payload.expires_at)

    latest = _get_latest_secret_map(db, environment_id=environment.id).get(key)
    if latest is None or latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret not found. Use the create endpoint instead.",
        )

    if decrypt_secret_value(latest.encrypted_value) == payload.value and latest.expires_at == expires_at:
        return SecretMutationResponse(
            project_id=project_access.project.id,
            environment_id=environment.id,
            key=key,
            version=latest.version,
            updated_at=latest.updated_at,
            expires_at=_serialize_secret_expiration(latest.expires_at),
            changed=False,
        )

    secret = _create_secret_version(
        db=db,
        environment_id=environment.id,
        key=key,
        value=payload.value,
        version=latest.version + 1,
        updated_by=current_user.id,
        expires_at=expires_at,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.updated",
        metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.updated")
    db.commit()
    db.refresh(secret)
    dispatch_webhooks(webhook_targets, event="secret.updated", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None})
    return SecretMutationResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        version=secret.version,
        updated_at=secret.updated_at,
        expires_at=_serialize_secret_expiration(secret.expires_at),
        changed=True,
    )


@router.delete(
    "/{project_id}/environments/{environment_id}/secrets/{secret_key}",
    response_model=SecretDeleteResponse,
)
def delete_secret(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    secret_key: str,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretDeleteResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    key = _validate_secret_key(secret_key)

    latest = _get_latest_secret_map(db, environment_id=environment.id).get(key)
    if latest is None or latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret not found.",
        )

    secret = _create_secret_version(
        db=db,
        environment_id=environment.id,
        key=key,
        value="",
        version=latest.version + 1,
        updated_by=current_user.id,
        expires_at=latest.expires_at,
        is_deleted=True,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.deleted",
        metadata={"key": key, "version": secret.version},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.deleted")
    db.commit()
    db.refresh(secret)
    dispatch_webhooks(webhook_targets, event="secret.deleted", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version})
    return SecretDeleteResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        version=secret.version,
        deleted_at=secret.updated_at,
    )


@router.post(
    "/{project_id}/secrets/bulk-delete",
    response_model=MessageResponse,
)
def bulk_delete_secrets(
    project_id: uuid.UUID,
    payload: SecretBulkDeleteRequest,
    project_access: ProjectAccess = Depends(require_secret_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    seen: set[tuple[uuid.UUID, str]] = set()
    normalized_items: list[tuple[uuid.UUID, str]] = []
    for item in payload.items:
        normalized_key = _validate_secret_key(item.key)
        item_key = (item.environment_id, normalized_key)
        if item_key in seen:
            continue
        seen.add(item_key)
        normalized_items.append(item_key)

    environments_by_id: dict[uuid.UUID, Environment] = {}
    latest_by_environment: dict[uuid.UUID, dict[str, Secret]] = {}
    to_delete: list[tuple[Environment, Secret, str]] = []

    for environment_id, key in normalized_items:
        environment = environments_by_id.get(environment_id)
        if environment is None:
            environment = get_project_environment_or_404(
                db,
                project=project_access.project,
                environment_id=environment_id,
            )
            environments_by_id[environment_id] = environment
            latest_by_environment[environment_id] = _get_latest_secret_map(
                db,
                environment_id=environment_id,
            )

        latest = latest_by_environment[environment_id].get(key)
        if latest is None or latest.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f'Secret "{key}" not found in environment "{environment.name}".',
            )
        to_delete.append((environment, latest, key))

    deleted_keys: list[str] = []
    webhook_payloads: list[tuple[uuid.UUID, dict[str, str | int | None]]] = []
    for environment, latest, key in to_delete:
        deleted = _create_secret_version(
            db=db,
            environment_id=environment.id,
            key=key,
            value="",
            version=latest.version + 1,
            updated_by=current_user.id,
            expires_at=latest.expires_at,
            is_deleted=True,
        )
        deleted_keys.append(f"{environment.name}:{key}")
        metadata = {"key": key, "version": deleted.version}
        write_audit_log(
            db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            user_id=current_user.id,
            action="secret.deleted",
            metadata=metadata,
        )
        webhook_payloads.append((environment.id, metadata))

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="secrets.bulk_deleted",
        metadata={"count": len(to_delete), "items": deleted_keys},
    )
    webhook_targets = get_webhooks_for_event(
        db,
        project_id=project_access.project.id,
        action="secret.deleted",
    )
    db.commit()

    for environment_id, metadata in webhook_payloads:
        dispatch_webhooks(
            webhook_targets,
            event="secret.deleted",
            project_id=project_access.project.id,
            environment_id=environment_id,
            actor_user_id=current_user.id,
            metadata=metadata,
        )

    return MessageResponse(detail=f"Deleted {len(to_delete)} secret(s).")
