from __future__ import annotations

from datetime import datetime
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_runtime_token_management
from app.api.pagination import paginate_items
from app.core.config import settings
from app.db.session import get_db
from app.models.machine_identity import MachineIdentity
from app.models.user import User
from app.schemas.machine_identity import (
    MachineIdentityCreate,
    MachineIdentityCredentialResponse,
    MachineIdentityRead,
    MachineIdentityRotateSecretRequest,
    MachineIdentityUpdate,
    MachineSecretsResponse,
    MachineTokenRequest,
    MachineTokenResponse,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.machine_identities import (
    MACHINE_SECRET_READ_ACTION,
    generate_machine_client_id,
    generate_machine_client_secret,
    get_machine_identity_by_client_id,
    hash_machine_client_secret,
    is_client_ip_allowed,
    is_machine_identity_active,
    issue_machine_access_token,
    normalize_secret_key_patterns,
    normalize_trusted_cidrs,
    resolve_machine_identity_from_access_token,
    secret_key_is_allowed,
    utcnow,
    validate_access_token_ttl,
    validate_credential_expiry,
    verify_machine_client_secret,
)
from app.services.access_control import evaluate_permission, subject_has_assignments
from app.models.project import Project
from app.services.secrets import build_secret_payload, get_latest_secret_rows


router = APIRouter()
machine_bearer_scheme = HTTPBearer(auto_error=False)


def _serialize_identity(identity: MachineIdentity) -> MachineIdentityRead:
    return MachineIdentityRead(
        id=identity.id,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        name=identity.name,
        client_id=identity.client_id,
        credential_version=identity.credential_version,
        credential_expires_at=identity.credential_expires_at,
        access_token_ttl_seconds=identity.access_token_ttl_seconds,
        allowed_actions=list(identity.allowed_actions),
        allowed_secret_keys=(
            list(identity.allowed_secret_keys)
            if identity.allowed_secret_keys is not None
            else None
        ),
        trusted_cidrs=list(identity.trusted_cidrs or []),
        created_by=identity.created_by,
        revoked_at=identity.revoked_at,
        last_authenticated_at=identity.last_authenticated_at,
        last_used_at=identity.last_used_at,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )


def _credential_response(
    identity: MachineIdentity,
    *,
    client_secret: str,
) -> MachineIdentityCredentialResponse:
    return MachineIdentityCredentialResponse(
        **_serialize_identity(identity).model_dump(),
        client_secret=client_secret,
    )


def _get_identity_or_404(
    db: Session,
    *,
    project_id: uuid.UUID,
    identity_id: uuid.UUID,
) -> MachineIdentity:
    identity = db.get(MachineIdentity, identity_id)
    if identity is None or identity.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine identity not found.",
        )
    return identity


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


@router.get(
    "/projects/{project_id}/machine-identities",
    response_model=list[MachineIdentityRead],
)
def list_machine_identities(
    response: Response = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    db: Session = Depends(get_db),
) -> list[MachineIdentityRead]:
    identities = db.scalars(
        select(MachineIdentity)
        .where(MachineIdentity.project_id == project_access.project.id)
        .order_by(MachineIdentity.created_at.asc())
    ).all()
    return paginate_items(
        [_serialize_identity(identity) for identity in identities],
        limit=limit,
        offset=offset,
        response=response,
    )


@router.post(
    "/projects/{project_id}/machine-identities",
    response_model=MachineIdentityCredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_machine_identity(
    payload: MachineIdentityCreate,
    response: Response,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineIdentityCredentialResponse:
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=payload.environment_id,
    )
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Machine identity name cannot be empty.",
        )
    try:
        ttl_seconds = validate_access_token_ttl(
            payload.access_token_ttl_seconds
            if payload.access_token_ttl_seconds is not None
            else settings.machine_auth_default_access_token_ttl_seconds
        )
        patterns = normalize_secret_key_patterns(payload.allowed_secret_keys)
        trusted_cidrs = normalize_trusted_cidrs(payload.trusted_cidrs)
        credential_expires_at = validate_credential_expiry(payload.credential_expires_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    client_secret = generate_machine_client_secret()
    identity = MachineIdentity(
        project_id=project_access.project.id,
        environment_id=environment.id,
        name=name,
        client_id=generate_machine_client_id(),
        client_secret_hash=hash_machine_client_secret(client_secret),
        credential_version=1,
        credential_expires_at=credential_expires_at,
        access_token_ttl_seconds=ttl_seconds,
        allowed_actions=list(payload.allowed_actions),
        allowed_secret_keys=patterns,
        trusted_cidrs=trusted_cidrs,
        created_by=current_user.id,
    )
    db.add(identity)
    db.flush()
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="machine_identity.created",
        metadata={
            "machine_identity_id": str(identity.id),
            "name": identity.name,
            "client_id": identity.client_id,
            "allowed_actions": identity.allowed_actions,
            "allowed_secret_keys": identity.allowed_secret_keys,
            "trusted_cidrs": identity.trusted_cidrs,
            "access_token_ttl_seconds": identity.access_token_ttl_seconds,
        },
    )
    db.commit()
    db.refresh(identity)
    _no_store(response)
    return _credential_response(identity, client_secret=client_secret)


@router.patch(
    "/projects/{project_id}/machine-identities/{identity_id}",
    response_model=MachineIdentityRead,
)
def update_machine_identity(
    identity_id: uuid.UUID,
    payload: MachineIdentityUpdate,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineIdentityRead:
    identity = _get_identity_or_404(
        db,
        project_id=project_access.project.id,
        identity_id=identity_id,
    )
    updates: dict[str, object] = {}
    try:
        if "name" in payload.model_fields_set and payload.name is not None:
            identity.name = payload.name.strip()
            if not identity.name:
                raise ValueError("Machine identity name cannot be empty.")
            updates["name"] = identity.name
        if "environment_id" in payload.model_fields_set and payload.environment_id is not None:
            environment = get_project_environment_or_404(
                db,
                project=project_access.project,
                environment_id=payload.environment_id,
            )
            identity.environment_id = environment.id
            updates["environment_id"] = str(environment.id)
        if "allowed_actions" in payload.model_fields_set and payload.allowed_actions is not None:
            identity.allowed_actions = list(payload.allowed_actions)
            updates["allowed_actions"] = identity.allowed_actions
        elif "allowed_actions" in payload.model_fields_set:
            raise ValueError("Allowed actions cannot be null.")
        if "allowed_secret_keys" in payload.model_fields_set:
            identity.allowed_secret_keys = normalize_secret_key_patterns(payload.allowed_secret_keys)
            updates["allowed_secret_keys"] = identity.allowed_secret_keys
        if "trusted_cidrs" in payload.model_fields_set:
            identity.trusted_cidrs = normalize_trusted_cidrs(payload.trusted_cidrs or [])
            updates["trusted_cidrs"] = identity.trusted_cidrs
        if "access_token_ttl_seconds" in payload.model_fields_set:
            if payload.access_token_ttl_seconds is None:
                raise ValueError("Access-token TTL cannot be null.")
            identity.access_token_ttl_seconds = validate_access_token_ttl(
                payload.access_token_ttl_seconds
            )
            updates["access_token_ttl_seconds"] = identity.access_token_ttl_seconds
        if "credential_expires_at" in payload.model_fields_set:
            identity.credential_expires_at = validate_credential_expiry(
                payload.credential_expires_at
            )
            updates["credential_expires_at"] = (
                identity.credential_expires_at.isoformat()
                if identity.credential_expires_at is not None
                else None
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=identity.environment_id,
        user_id=current_user.id,
        action="machine_identity.updated",
        metadata={"machine_identity_id": str(identity.id), **updates},
    )
    db.commit()
    db.refresh(identity)
    return _serialize_identity(identity)


@router.post(
    "/projects/{project_id}/machine-identities/{identity_id}/rotate-secret",
    response_model=MachineIdentityCredentialResponse,
)
def rotate_machine_identity_secret(
    identity_id: uuid.UUID,
    payload: MachineIdentityRotateSecretRequest,
    response: Response,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineIdentityCredentialResponse:
    identity = _get_identity_or_404(
        db,
        project_id=project_access.project.id,
        identity_id=identity_id,
    )
    if identity.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked machine identities cannot rotate credentials.",
        )
    try:
        credential_expires_at = (
            validate_credential_expiry(payload.credential_expires_at)
            if "credential_expires_at" in payload.model_fields_set
            else identity.credential_expires_at
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    client_secret = generate_machine_client_secret()
    identity.client_secret_hash = hash_machine_client_secret(client_secret)
    identity.credential_version += 1
    identity.credential_expires_at = credential_expires_at
    write_audit_log(
        db,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        user_id=current_user.id,
        action="machine_identity.credential_rotated",
        metadata={
            "machine_identity_id": str(identity.id),
            "credential_version": identity.credential_version,
        },
    )
    db.commit()
    db.refresh(identity)
    _no_store(response)
    return _credential_response(identity, client_secret=client_secret)


@router.post(
    "/projects/{project_id}/machine-identities/{identity_id}/revoke",
    response_model=MachineIdentityRead,
)
def revoke_machine_identity(
    identity_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineIdentityRead:
    identity = _get_identity_or_404(
        db,
        project_id=project_access.project.id,
        identity_id=identity_id,
    )
    if identity.revoked_at is None:
        identity.revoked_at = utcnow()
        identity.credential_version += 1
        write_audit_log(
            db,
            project_id=identity.project_id,
            environment_id=identity.environment_id,
            user_id=current_user.id,
            action="machine_identity.revoked",
            metadata={"machine_identity_id": str(identity.id)},
        )
        db.commit()
        db.refresh(identity)
    return _serialize_identity(identity)


@router.post(
    "/machine-identities/token",
    response_model=MachineTokenResponse,
)
def exchange_machine_identity_token(
    payload: MachineTokenRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MachineTokenResponse:
    identity = get_machine_identity_by_client_id(db, client_id=payload.client_id)
    if (
        identity is None
        or not verify_machine_client_secret(
            plaintext=payload.client_secret,
            stored_hash=identity.client_secret_hash,
        )
        or not is_machine_identity_active(identity)
        or not is_client_ip_allowed(
            client_ip=_client_ip(request),
            trusted_cidrs=list(identity.trusted_cidrs or []),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid machine credentials.",
        )

    try:
        issued = issue_machine_access_token(identity)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid machine credentials.",
        ) from exc
    identity.last_authenticated_at = utcnow()
    write_audit_log(
        db,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        user_id=None,
        action="machine_identity.authenticated",
        metadata={
            "machine_identity_id": str(identity.id),
            "client_id": identity.client_id,
        },
    )
    db.commit()
    _no_store(response)
    return MachineTokenResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        expires_at=issued.expires_at,
    )


@router.get("/machine/secrets", response_model=MachineSecretsResponse)
def fetch_machine_secrets(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(machine_bearer_scheme),
    db: Session = Depends(get_db),
) -> MachineSecretsResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Machine access token is required.",
        )
    try:
        identity = resolve_machine_identity_from_access_token(
            db,
            access_token=credentials.credentials,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid machine access token.",
        ) from exc

    if not is_client_ip_allowed(
        client_ip=_client_ip(request),
        trusted_cidrs=list(identity.trusted_cidrs or []),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Machine access is not allowed from this IP address.",
        )
    if MACHINE_SECRET_READ_ACTION not in identity.allowed_actions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Machine identity is not allowed to read secrets.",
        )

    latest_rows = get_latest_secret_rows(db, environment_id=identity.environment_id)
    project = db.get(Project, identity.project_id)
    uses_rbac = project is not None and subject_has_assignments(
        db, project=project, machine_identity_id=identity.id
    )
    scoped_rows = [
        row
        for row in latest_rows
        if secret_key_is_allowed(key=row.key, patterns=identity.allowed_secret_keys)
        and (
            not uses_rbac
            or evaluate_permission(
                db,
                project=project,
                machine_identity_id=identity.id,
                resource="secrets",
                action="read",
                environment_id=identity.environment_id,
                path=row.path,
            ).allowed
        )
    ]
    if uses_rbac and not scoped_rows:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Machine identity has no matching permission to read secrets.",
        )
    try:
        secrets, _versions = build_secret_payload(
            db,
            project_id=identity.project_id,
            secret_rows=scoped_rows,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc

    now = utcnow()
    identity.last_used_at = now
    write_audit_log(
        db,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        user_id=None,
        action="machine_identity.secrets_accessed",
        metadata={
            "machine_identity_id": str(identity.id),
            "secret_keys": sorted(secrets),
            "secret_count": len(secrets),
        },
    )
    db.commit()
    _no_store(response)
    return MachineSecretsResponse(
        machine_identity_id=identity.id,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        secrets=secrets,
        generated_at=now,
    )
