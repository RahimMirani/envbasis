from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ProjectAccess,
    enforce_project_permission,
    enforce_machine_secret_key,
    machine_secret_key_allowed,
    get_current_user,
    get_project_access,
    require_secret_management,
)
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
    ResolvedSecretItem,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.project_encryption import decrypt_project_secret, encrypt_project_secret
from app.services.webhooks import dispatch_webhooks, get_webhooks_for_event
from app.services.secrets import (
    MAX_SECRET_KEY_LENGTH,
    build_secret_payload,
    get_latest_secret_rows,
    get_latest_project_secret_rows,
    get_project_secret_stats,
    validate_single_secret,
)
from app.services.secret_structure import (
    ensure_project_tags,
    ensure_secret_folder,
    normalize_secret_path,
    normalize_secret_tags,
)
from app.services.secret_resolution import (
    SecretReferenceCycleError,
    contains_reference,
    resolve_secret_values,
    validate_reference_cycles,
)
from app.services.secret_history import archive_old_secret_versions
from app.services.approvals import get_matching_approval_policy

router = APIRouter(prefix="/projects")


def _require_direct_change_allowed(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str,
    operation: str,
) -> None:
    policy = get_matching_approval_policy(
        db,
        project_id=project_id,
        environment_id=environment_id,
        path=path,
        operation=operation,
    )
    if policy is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "approval_required",
                "message": "This secret change must be submitted for approval.",
                "policy_id": str(policy.id),
                "submit_url": f"/projects/{project_id}/approval-requests",
            },
        )


def _validate_secret_key(key: str) -> str:
    normalized = key.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Secret keys cannot be empty.",
        )
    if len(normalized) > MAX_SECRET_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Secret key is too long. Maximum length is {MAX_SECRET_KEY_LENGTH}.",
        )
    return normalized


def _validate_secret_value(*, key: str, value: str) -> None:
    try:
        validate_single_secret(key=key, value=value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _normalize_secret_path(value: str) -> str:
    try:
        return normalize_secret_path(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _normalize_secret_tags(values: list[str]) -> list[str]:
    try:
        return normalize_secret_tags(values)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    key: str,
    value: str,
    version: int,
    updated_by: uuid.UUID,
    expires_at: datetime | None = None,
    is_deleted: bool = False,
    path: str = "/",
    tags: list[str] | None = None,
    description: str | None = None,
    owner: str | None = None,
    service: str | None = None,
    rotation_interval_days: int | None = None,
    rotate_at: datetime | None = None,
    custom_metadata: dict[str, str] | None = None,
    is_reference: bool | None = None,
) -> Secret:
    ensure_secret_folder(
        db,
        environment_id=environment_id,
        path=path,
        created_by=updated_by,
    )
    ensure_project_tags(
        db,
        project_id=project_id,
        tags=list(tags or []),
        created_by=updated_by,
    )
    encrypted_value, encryption_key_version = encrypt_project_secret(
        db,
        project_id=project_id,
        value="" if is_deleted else value,
    )
    secret = Secret(
        environment_id=environment_id,
        key=key,
        path=path,
        tags=list(tags or []),
        description=description,
        owner=owner,
        service=service,
        rotation_interval_days=rotation_interval_days,
        rotate_at=rotate_at,
        custom_metadata=dict(custom_metadata or {}),
        is_reference=contains_reference(value) if is_reference is None else is_reference,
        encrypted_value=encrypted_value,
        encryption_key_version=encryption_key_version,
        version=version,
        is_deleted=is_deleted,
        updated_by=updated_by,
        expires_at=expires_at,
    )
    db.add(secret)
    db.flush()
    archive_old_secret_versions(
        db,
        project_id=project_id,
        environment_id=environment_id,
        path=path,
        key=key,
    )
    return secret


def _validate_reference_graph_or_422(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str,
) -> None:
    try:
        validate_reference_cycles(
            db,
            project_id=project_id,
            environment_id=environment_id,
            path=path,
        )
    except SecretReferenceCycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "secret_reference_cycle", "message": str(exc), "cycle": exc.cycle},
        ) from exc


def _get_latest_secret_map(
    db: Session,
    *,
    environment_id: uuid.UUID,
) -> dict[tuple[str, str], Secret]:
    return {
        (secret.path, secret.key): secret
        for secret in get_latest_secret_rows(
            db,
            environment_id=environment_id,
            include_deleted=True,
        )
    }


def _resolve_latest_secret(
    latest_by_location: dict[tuple[str, str], Secret],
    *,
    key: str,
    path: str | None,
) -> tuple[str, Secret | None]:
    if path is not None:
        selected_path = _normalize_secret_path(path)
        return selected_path, latest_by_location.get((selected_path, key))

    candidates = [
        secret
        for (candidate_path, candidate_key), secret in latest_by_location.items()
        if candidate_key == key and not secret.is_deleted
    ]
    if len(candidates) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="More than one secret has this key. Specify its path.",
        )
    if not candidates:
        return "/", None
    return candidates[0].path, candidates[0]


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
    project_access: ProjectAccess = Depends(require_secret_management),
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
    secret_path = _normalize_secret_path(payload.path)
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        path=secret_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )

    latest_by_key = _get_latest_secret_map(db, environment_id=environment.id)
    secret_tags = _normalize_secret_tags(payload.tags)
    for raw_key, raw_value in payload.secrets.items():
        candidate_key = _validate_secret_key(raw_key)
        candidate_latest = latest_by_key.get((secret_path, candidate_key))
        candidate_unchanged = (
            candidate_latest is not None
            and not candidate_latest.is_deleted
            and decrypt_project_secret(
                db,
                project_id=project_access.project.id,
                encrypted_value=candidate_latest.encrypted_value,
                encryption_key_version=candidate_latest.encryption_key_version,
            )
            == raw_value
            and candidate_latest.tags == secret_tags
            and candidate_latest.description == payload.description
            and candidate_latest.owner == payload.owner
            and candidate_latest.service == payload.service
            and candidate_latest.rotation_interval_days == payload.rotation_interval_days
            and candidate_latest.rotate_at == payload.rotate_at
            and candidate_latest.custom_metadata == payload.custom_metadata
        )
        if candidate_unchanged:
            continue
        _require_direct_change_allowed(
            db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            path=secret_path,
            operation=(
                "create"
                if candidate_latest is None or candidate_latest.is_deleted
                else "update"
            ),
        )
    versions: list[SecretVersionRead] = []
    changed = 0
    unchanged = 0
    changed_keys: list[str] = []

    for raw_key, raw_value in payload.secrets.items():
        key = _validate_secret_key(raw_key)
        value = raw_value
        latest = latest_by_key.get((secret_path, key))

        if (
            latest is not None
            and not latest.is_deleted
            and decrypt_project_secret(
                db,
                project_id=project_access.project.id,
                encrypted_value=latest.encrypted_value,
                encryption_key_version=latest.encryption_key_version,
            )
            == value
            and latest.path == secret_path
            and latest.tags == secret_tags
            and latest.description == payload.description
            and latest.owner == payload.owner
            and latest.service == payload.service
            and latest.rotation_interval_days == payload.rotation_interval_days
            and latest.rotate_at == payload.rotate_at
            and latest.custom_metadata == payload.custom_metadata
        ):
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
            project_id=project_access.project.id,
            environment_id=environment.id,
            key=key,
            value=value,
            version=version,
            updated_by=current_user.id,
            path=secret_path,
            tags=secret_tags,
            description=payload.description,
            owner=payload.owner,
            service=payload.service,
            rotation_interval_days=payload.rotation_interval_days,
            rotate_at=payload.rotate_at,
            custom_metadata=payload.custom_metadata,
        )
        latest_by_key[(secret_path, key)] = secret
        changed += 1
        changed_keys.append(key)
        versions.append(
            SecretVersionRead(
                key=key,
                version=secret.version,
                updated_at=secret.updated_at,
            )
        )

    if changed:
        _validate_reference_graph_or_422(
            db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            path=secret_path,
        )

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.pushed",
        metadata={"changed_keys": changed_keys, "changed_count": changed, "unchanged_count": unchanged, "path": secret_path, "tags": secret_tags},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secrets.pushed")
    dispatch_webhooks(webhook_targets, db=db, event="secrets.pushed", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"changed_keys": changed_keys, "changed_count": changed, "unchanged_count": unchanged})
    db.commit()
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
    project_access: ProjectAccess = Depends(get_project_access),  # any member can see stats
    db: Session = Depends(get_db),
) -> ProjectSecretStatsResponse:
    if project_access.subject_machine_id is not None and project_access.machine_allowed_secret_keys is not None:
        raise HTTPException(status_code=403, detail="Scoped machine identities cannot access aggregate secret statistics.")
    enforce_project_permission(
        db, project_access=project_access, resource="secrets", action="list", legacy_allowed=True
    )
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
    path: Annotated[str | None, Query(max_length=512)] = None,
    recursive: bool = False,
    tag: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Maximum number of secrets to return."),
    ] = 50,
    cursor: Annotated[
        str | None,
        Query(description="Offset cursor returned by a previous project secrets listing."),
    ] = None,
    project_access: ProjectAccess = Depends(get_project_access),  # any member can list keys
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectSecretListResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    try:
        offset = int(cursor) if cursor else 0
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid cursor.",
        ) from exc

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid cursor.",
        )

    selected_path = _normalize_secret_path(path) if path is not None else None
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="list",
        environment_id=environment_id[0] if environment_id and len(environment_id) == 1 else None,
        path=selected_path,
        legacy_allowed=True,
    )
    selected_tags = _normalize_secret_tags(tag or [])
    rows, next_cursor = get_latest_project_secret_rows(
        db,
        project_id=project_access.project.id,
        environment_ids=environment_id,
        key_filter=key,
        path=selected_path,
        recursive=recursive,
        tags=selected_tags,
        limit=limit,
        offset=offset,
    )
    rows = [(secret, environment) for secret, environment in rows if machine_secret_key_allowed(project_access, secret.key)]
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
            "path": selected_path,
            "recursive": recursive,
            "tags": selected_tags,
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
                path=secret.path,
                tags=secret.tags,
                description=secret.description,
                owner=secret.owner,
                service=secret.service,
                rotation_interval_days=secret.rotation_interval_days,
                rotate_at=_serialize_secret_expiration(secret.rotate_at),
                custom_metadata=secret.custom_metadata,
                is_reference=secret.is_reference,
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
    response: Response = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    key: Annotated[
        str | None,
        Query(
            max_length=128,
            description="Filter secrets by key (case-insensitive substring match)",
        ),
    ] = None,
    path: Annotated[str | None, Query(max_length=512)] = None,
    recursive: bool = False,
    tag: Annotated[list[str] | None, Query()] = None,
    project_access: ProjectAccess = Depends(get_project_access),  # any member can list keys
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

    selected_path = _normalize_secret_path(path) if path is not None else None
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="list",
        environment_id=environment.id,
        path=selected_path,
        legacy_allowed=True,
    )
    selected_tags = _normalize_secret_tags(tag or [])
    all_latest_rows = get_latest_secret_rows(
        db,
        environment_id=environment.id,
        key_filter=key,
        path=selected_path,
        recursive=recursive,
        tags=selected_tags,
    )
    all_latest_rows = [row for row in all_latest_rows if machine_secret_key_allowed(project_access, row.key)]
    if response is not None:
        response.headers["X-Total-Count"] = str(len(all_latest_rows))
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    latest_rows = all_latest_rows[offset : offset + limit]
    users_by_id = _get_users_by_id(db, latest_rows)

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.listed",
        metadata={"secret_count": len(latest_rows), "path": selected_path, "recursive": recursive, "tags": selected_tags},
    )
    db.commit()

    return SecretListResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        secrets=[
            SecretItemRead(
                key=row.key,
                path=row.path,
                tags=row.tags,
                description=row.description,
                owner=row.owner,
                service=row.service,
                rotation_interval_days=row.rotation_interval_days,
                rotate_at=_serialize_secret_expiration(row.rotate_at),
                custom_metadata=row.custom_metadata,
                is_reference=row.is_reference,
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
    path: Annotated[str | None, Query(max_length=512)] = None,
    project_access: ProjectAccess = Depends(require_secret_management),
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
    enforce_machine_secret_key(project_access, key)
    selected_path, latest = _resolve_latest_secret(
        _get_latest_secret_map(db, environment_id=environment.id), key=key, path=path
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="read",
        environment_id=environment.id,
        path=selected_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )
    if latest is None or latest.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found.")

    users_by_id = _get_users_by_id(db, [latest])
    value = decrypt_project_secret(
        db,
        project_id=project_access.project.id,
        encrypted_value=latest.encrypted_value,
        encryption_key_version=latest.encryption_key_version,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.revealed",
        metadata={"secret_key": key, "path": selected_path, "version": latest.version},
    )
    db.commit()

    return SecretRevealResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        value=value,
        path=latest.path,
        tags=latest.tags,
        description=latest.description,
        owner=latest.owner,
        service=latest.service,
        rotation_interval_days=latest.rotation_interval_days,
        rotate_at=_serialize_secret_expiration(latest.rotate_at),
        custom_metadata=latest.custom_metadata,
        is_reference=latest.is_reference,
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
    path: Annotated[str, Query(max_length=512)] = "/",
    tag: Annotated[list[str] | None, Query()] = None,
    recursive: bool = False,
    resolve_references: Annotated[bool, Query(alias="resolve")] = True,
    include_imports: bool = True,
    project_access: ProjectAccess = Depends(require_secret_management),
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

    selected_path = _normalize_secret_path(path)
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="read",
        environment_id=environment.id,
        path=selected_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )
    selected_tags = set(_normalize_secret_tags(tag or []))
    try:
        resolved_items = resolve_secret_values(
            db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            path=selected_path,
            recursive=recursive,
            include_imports=include_imports,
            resolve_references=resolve_references,
            tags=sorted(selected_tags),
        )
    except SecretReferenceCycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "secret_reference_cycle", "message": str(exc), "cycle": exc.cycle},
        ) from exc
    resolved_items = [item for item in resolved_items if machine_secret_key_allowed(project_access, item.key)]
    secrets = {item.key: item.value for item in resolved_items}
    versions = {item.key: item.version for item in resolved_items}
    resolution_errors = [f"{item.key}: {item.error}" for item in resolved_items if item.error]

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secrets.pulled",
        metadata={"secret_count": len(secrets), "path": selected_path, "recursive": recursive, "tags": sorted(selected_tags), "resolve": resolve_references, "include_imports": include_imports, "resolution_error_count": len(resolution_errors)},
    )
    db.commit()

    return SecretPullResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        secrets=secrets,
        versions=versions,
        items=[ResolvedSecretItem(**item.__dict__) for item in resolved_items],
        resolution_mode="resolved" if resolve_references else "unresolved",
        includes_imports=include_imports,
        resolution_errors=resolution_errors,
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
    project_access: ProjectAccess = Depends(require_secret_management),
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
    secret_path = _normalize_secret_path(payload.path)
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        path=secret_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )
    secret_tags = _normalize_secret_tags(payload.tags)

    latest_by_key = _get_latest_secret_map(db, environment_id=environment.id)
    latest = latest_by_key.get((secret_path, key))
    if latest is not None and not latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Secret already exists. Use the update endpoint instead.",
        )
    _require_direct_change_allowed(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=secret_path,
        operation="create",
    )

    version = 1 if latest is None else latest.version + 1
    secret = _create_secret_version(
        db=db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        value=payload.value,
        version=version,
        updated_by=current_user.id,
        expires_at=expires_at,
        path=secret_path,
        tags=secret_tags,
        description=payload.description,
        owner=payload.owner,
        service=payload.service,
        rotation_interval_days=payload.rotation_interval_days,
        rotate_at=payload.rotate_at,
        custom_metadata=payload.custom_metadata,
    )
    _validate_reference_graph_or_422(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=secret_path,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.created",
        metadata={"key": key, "path": secret_path, "tags": secret_tags, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.created")
    dispatch_webhooks(webhook_targets, db=db, event="secret.created", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None})
    db.commit()
    db.refresh(secret)
    return SecretMutationResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        path=secret.path,
        tags=secret.tags,
        description=secret.description,
        owner=secret.owner,
        service=secret.service,
        rotation_interval_days=secret.rotation_interval_days,
        rotate_at=_serialize_secret_expiration(secret.rotate_at),
        custom_metadata=secret.custom_metadata,
        is_reference=secret.is_reference,
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
    path: Annotated[str | None, Query(max_length=512)] = None,
    project_access: ProjectAccess = Depends(require_secret_management),
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

    selected_path, latest = _resolve_latest_secret(
        _get_latest_secret_map(db, environment_id=environment.id), key=key, path=path
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        path=selected_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )
    if latest is None or latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret not found. Use the create endpoint instead.",
        )
    _require_direct_change_allowed(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=selected_path,
        operation="update",
    )

    secret_path = _normalize_secret_path(payload.path if payload.path is not None else latest.path)
    if secret_path != latest.path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A secret cannot be moved by updating it. Create it at the new path, then delete the old secret.",
        )
    secret_tags = _normalize_secret_tags(payload.tags if payload.tags is not None else list(latest.tags or []))
    fields_set = payload.model_fields_set
    description = payload.description if "description" in fields_set else latest.description
    owner = payload.owner if "owner" in fields_set else latest.owner
    service = payload.service if "service" in fields_set else latest.service
    rotation_interval_days = (
        payload.rotation_interval_days
        if "rotation_interval_days" in fields_set
        else latest.rotation_interval_days
    )
    rotate_at = payload.rotate_at if "rotate_at" in fields_set else latest.rotate_at
    custom_metadata = (
        dict(payload.custom_metadata or {})
        if "custom_metadata" in fields_set
        else dict(latest.custom_metadata or {})
    )

    if (
        decrypt_project_secret(
            db,
            project_id=project_access.project.id,
            encrypted_value=latest.encrypted_value,
            encryption_key_version=latest.encryption_key_version,
        )
        == payload.value
        and latest.expires_at == expires_at
        and latest.path == secret_path
        and latest.tags == secret_tags
        and latest.description == description
        and latest.owner == owner
        and latest.service == service
        and latest.rotation_interval_days == rotation_interval_days
        and latest.rotate_at == rotate_at
        and latest.custom_metadata == custom_metadata
    ):
        return SecretMutationResponse(
            project_id=project_access.project.id,
            environment_id=environment.id,
            key=key,
            path=latest.path,
            tags=latest.tags,
            description=latest.description,
            owner=latest.owner,
            service=latest.service,
            rotation_interval_days=latest.rotation_interval_days,
            rotate_at=_serialize_secret_expiration(latest.rotate_at),
            custom_metadata=latest.custom_metadata,
            is_reference=latest.is_reference,
            version=latest.version,
            updated_at=latest.updated_at,
            expires_at=_serialize_secret_expiration(latest.expires_at),
            changed=False,
        )

    secret = _create_secret_version(
        db=db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        value=payload.value,
        version=latest.version + 1,
        updated_by=current_user.id,
        expires_at=expires_at,
        path=secret_path,
        tags=secret_tags,
        description=description,
        owner=owner,
        service=service,
        rotation_interval_days=rotation_interval_days,
        rotate_at=rotate_at,
        custom_metadata=custom_metadata,
    )
    _validate_reference_graph_or_422(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=secret_path,
    )
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.updated",
        metadata={"key": key, "path": secret_path, "tags": secret_tags, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.updated")
    dispatch_webhooks(webhook_targets, db=db, event="secret.updated", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version, "expires_at": expires_at.isoformat() if expires_at else None})
    db.commit()
    db.refresh(secret)
    return SecretMutationResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        path=secret.path,
        tags=secret.tags,
        description=secret.description,
        owner=secret.owner,
        service=secret.service,
        rotation_interval_days=secret.rotation_interval_days,
        rotate_at=_serialize_secret_expiration(secret.rotate_at),
        custom_metadata=secret.custom_metadata,
        is_reference=secret.is_reference,
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
    path: Annotated[str | None, Query(max_length=512)] = None,
    project_access: ProjectAccess = Depends(require_secret_management),
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
    selected_path, latest = _resolve_latest_secret(
        _get_latest_secret_map(db, environment_id=environment.id), key=key, path=path
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        path=selected_path,
        legacy_allowed=project_access.can_push_pull_secrets,
    )
    if latest is None or latest.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret not found.",
        )
    _require_direct_change_allowed(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=selected_path,
        operation="delete",
    )

    secret = _create_secret_version(
        db=db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        value="",
        version=latest.version + 1,
        updated_by=current_user.id,
        expires_at=latest.expires_at,
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
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret.deleted",
        metadata={"key": key, "path": selected_path, "version": secret.version},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="secret.deleted")
    dispatch_webhooks(webhook_targets, db=db, event="secret.deleted", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"key": key, "version": secret.version})
    db.commit()
    db.refresh(secret)
    return SecretDeleteResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        key=key,
        path=selected_path,
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
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    seen: set[tuple[uuid.UUID, str, str]] = set()
    normalized_items: list[tuple[uuid.UUID, str, str]] = []
    for item in payload.items:
        normalized_key = _validate_secret_key(item.key)
        normalized_path = _normalize_secret_path(item.path)
        item_key = (item.environment_id, normalized_path, normalized_key)
        if item_key in seen:
            continue
        seen.add(item_key)
        normalized_items.append(item_key)

    environments_by_id: dict[uuid.UUID, Environment] = {}
    latest_by_environment: dict[uuid.UUID, dict[str, Secret]] = {}
    to_delete: list[tuple[Environment, Secret, str]] = []

    for environment_id, selected_path, key in normalized_items:
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

        enforce_project_permission(
            db,
            project_access=project_access,
            resource="secrets",
            action="write",
            environment_id=environment_id,
            path=selected_path,
            legacy_allowed=project_access.can_push_pull_secrets,
        )

        latest = latest_by_environment[environment_id].get((selected_path, key))
        if latest is None or latest.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f'Secret "{key}" not found in environment "{environment.name}".',
            )
        _require_direct_change_allowed(
            db,
            project_id=project_access.project.id,
            environment_id=environment_id,
            path=selected_path,
            operation="delete",
        )
        to_delete.append((environment, latest, key))

    deleted_keys: list[str] = []
    webhook_payloads: list[tuple[uuid.UUID, dict[str, str | int | None]]] = []
    for environment, latest, key in to_delete:
        deleted = _create_secret_version(
            db=db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            key=key,
            value="",
            version=latest.version + 1,
            updated_by=current_user.id,
            expires_at=latest.expires_at,
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
        deleted_keys.append(f"{environment.name}:{latest.path}:{key}")
        metadata = {"key": key, "path": latest.path, "version": deleted.version}
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
    for environment_id, metadata in webhook_payloads:
        dispatch_webhooks(
            webhook_targets,
            db=db,
            event="secret.deleted",
            project_id=project_access.project.id,
            environment_id=environment_id,
            actor_user_id=current_user.id,
            metadata=metadata,
        )
    db.commit()

    return MessageResponse(detail=f"Deleted {len(to_delete)} secret(s).")
