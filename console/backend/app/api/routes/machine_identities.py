from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_runtime_token_management
from app.api.pagination import paginate_items
from app.core.config import settings
from app.db.session import get_db
from app.models.machine_identity import MachineIdentity
from app.models.machine_identity_credential import MachineIdentityAuthEvent, MachineIdentityCredential
from app.models.organization import Organization
from app.models.user import User
from app.schemas.machine_identity import (
    MachineIdentityCreate,
    MachineIdentityCredentialResponse,
    MachineIdentityRead,
    MachineIdentityRotateSecretRequest,
    MachineIdentityUpdate,
    MachineCredentialCreate,
    MachineCredentialRead,
    MachineCredentialResponse,
    MachineAuthEventRead,
    MachineSecretsResponse,
    MachineTokenRequest,
    MachineTokenResponse,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.machine_identities import (
    MACHINE_SECRET_READ_ACTION,
    as_utc,
    generate_machine_client_id,
    generate_machine_client_secret,
    get_machine_identity_by_client_id,
    get_machine_credential_by_client_id,
    hash_machine_client_secret,
    is_client_ip_allowed,
    is_machine_identity_active,
    is_machine_credential_active,
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


def _serialize_credential(credential: MachineIdentityCredential) -> MachineCredentialRead:
    return MachineCredentialRead(
        id=credential.id,
        identity_id=credential.identity_id,
        name=credential.name,
        auth_method=credential.auth_method,
        client_id=credential.client_id,
        version=credential.version,
        expires_at=credential.expires_at,
        overlap_expires_at=credential.overlap_expires_at,
        revoked_at=credential.revoked_at,
        last_authenticated_at=credential.last_authenticated_at,
        created_at=credential.created_at,
    )


def _identity_credentials(db: Session | None, identity_id: uuid.UUID) -> list[MachineCredentialRead]:
    if db is None:
        return []
    rows = db.scalars(select(MachineIdentityCredential).where(MachineIdentityCredential.identity_id == identity_id).order_by(MachineIdentityCredential.created_at)).all()
    return [_serialize_credential(row) for row in rows]


def _serialize_identity(identity: MachineIdentity, db: Session | None = None) -> MachineIdentityRead:
    return MachineIdentityRead(
        id=identity.id,
        project_id=identity.project_id,
        organization_id=identity.organization_id,
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
        disabled_at=identity.disabled_at,
        locked_until=identity.locked_until,
        failed_auth_attempts=identity.failed_auth_attempts,
        credentials=_identity_credentials(db, identity.id),
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
    project = db.get(Project, project_id)
    if identity is None or project is None or not (
        identity.project_id == project_id
        or (project.organization_id is not None and identity.organization_id == project.organization_id)
    ):
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
        .where(
            or_(
                MachineIdentity.project_id == project_access.project.id,
                MachineIdentity.organization_id == project_access.project.organization_id
                if project_access.project.organization_id is not None
                else MachineIdentity.id.is_(None),
            )
        )
        .order_by(MachineIdentity.created_at.asc())
    ).all()
    return paginate_items(
        [_serialize_identity(identity, db) for identity in identities],
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
    environment = (
        get_project_environment_or_404(db, project=project_access.project, environment_id=payload.environment_id)
        if payload.environment_id is not None
        else None
    )
    organization_id = None
    project_id: uuid.UUID | None = project_access.project.id
    if payload.scope == "organization":
        organization_id = project_access.project.organization_id
        organization = db.get(Organization, organization_id) if organization_id else None
        if organization is None or organization.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the organization owner can create an organization-scoped identity.")
        project_id = None
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
        project_id=project_id,
        organization_id=organization_id,
        environment_id=environment.id if environment else None,
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
    credential = MachineIdentityCredential(
        identity_id=identity.id,
        name="default",
        auth_method="universal-auth",
        client_id=identity.client_id,
        client_secret_hash=identity.client_secret_hash,
        version=1,
        expires_at=credential_expires_at,
        created_by=current_user.id,
    )
    db.add(credential)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id if environment else None,
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
    return MachineIdentityCredentialResponse(
        **_serialize_identity(identity, db).model_dump(), client_secret=client_secret
    )


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
    return _serialize_identity(identity, db)


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

    old_credential = (
        db.get(MachineIdentityCredential, payload.credential_id)
        if payload.credential_id is not None
        else db.scalar(
            select(MachineIdentityCredential)
            .where(MachineIdentityCredential.identity_id == identity.id, MachineIdentityCredential.revoked_at.is_(None))
            .order_by(MachineIdentityCredential.created_at.desc())
        )
    )
    if old_credential is None or old_credential.identity_id != identity.id:
        raise HTTPException(status_code=404, detail="Machine credential not found.")
    overlap_seconds = (
        payload.overlap_seconds
        if payload.overlap_seconds is not None
        else settings.machine_auth_default_rotation_overlap_seconds
    )
    now = utcnow()
    if overlap_seconds:
        old_credential.overlap_expires_at = now + timedelta(seconds=overlap_seconds)
    else:
        old_credential.revoked_at = now
    client_secret = generate_machine_client_secret()
    next_client_id = generate_machine_client_id()
    new_credential = MachineIdentityCredential(
        identity_id=identity.id,
        name=old_credential.name,
        auth_method="universal-auth",
        client_id=next_client_id,
        client_secret_hash=hash_machine_client_secret(client_secret),
        version=old_credential.version + 1,
        expires_at=credential_expires_at,
        created_by=current_user.id,
    )
    db.add(new_credential)
    identity.client_id = next_client_id
    identity.client_secret_hash = new_credential.client_secret_hash
    identity.credential_version += 1
    identity.credential_expires_at = credential_expires_at
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=identity.environment_id,
        user_id=current_user.id,
        action="machine_identity.credential_rotated",
        metadata={
            "machine_identity_id": str(identity.id),
            "credential_version": identity.credential_version,
            "overlap_seconds": overlap_seconds,
            "previous_credential_id": str(old_credential.id),
        },
    )
    db.commit()
    db.refresh(identity)
    _no_store(response)
    return MachineIdentityCredentialResponse(
        **_serialize_identity(identity, db).model_dump(), client_secret=client_secret
    )


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
        for credential in db.scalars(select(MachineIdentityCredential).where(MachineIdentityCredential.identity_id == identity.id, MachineIdentityCredential.revoked_at.is_(None))).all():
            credential.revoked_at = identity.revoked_at
        write_audit_log(
            db,
            project_id=project_access.project.id,
            environment_id=identity.environment_id,
            user_id=current_user.id,
            action="machine_identity.revoked",
            metadata={"machine_identity_id": str(identity.id)},
        )
        db.commit()
        db.refresh(identity)
    return _serialize_identity(identity, db)


@router.post(
    "/projects/{project_id}/machine-identities/{identity_id}/credentials",
    response_model=MachineCredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_machine_credential(
    identity_id: uuid.UUID,
    payload: MachineCredentialCreate,
    response: Response,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineCredentialResponse:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    if identity.revoked_at or identity.disabled_at:
        raise HTTPException(status_code=409, detail="Inactive identities cannot create credentials.")
    try:
        expires_at = validate_credential_expiry(payload.credential_expires_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    credential_name = payload.name.strip()
    if not credential_name:
        raise HTTPException(status_code=422, detail="Credential name cannot be empty.")
    secret = generate_machine_client_secret()
    credential = MachineIdentityCredential(
        identity_id=identity.id,
        name=credential_name,
        auth_method="universal-auth",
        client_id=generate_machine_client_id(),
        client_secret_hash=hash_machine_client_secret(secret),
        expires_at=expires_at,
        created_by=current_user.id,
    )
    db.add(credential)
    db.flush()
    write_audit_log(db, project_id=project_access.project.id, environment_id=identity.environment_id, user_id=current_user.id, action="machine_identity.credential_created", metadata={"machine_identity_id": str(identity.id), "credential_id": str(credential.id), "name": credential.name})
    db.commit()
    db.refresh(credential)
    _no_store(response)
    return MachineCredentialResponse(**_serialize_credential(credential).model_dump(), client_secret=secret)


@router.delete(
    "/projects/{project_id}/machine-identities/{identity_id}/credentials/{credential_id}",
    response_model=MachineCredentialRead,
)
def revoke_machine_credential(
    identity_id: uuid.UUID,
    credential_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MachineCredentialRead:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    credential = db.get(MachineIdentityCredential, credential_id)
    if credential is None or credential.identity_id != identity.id:
        raise HTTPException(status_code=404, detail="Machine credential not found.")
    if credential.revoked_at is None:
        credential.revoked_at = utcnow()
        credential.version += 1
        write_audit_log(db, project_id=project_access.project.id, environment_id=identity.environment_id, user_id=current_user.id, action="machine_identity.credential_revoked", metadata={"machine_identity_id": str(identity.id), "credential_id": str(credential.id)})
        db.commit()
        db.refresh(credential)
    return _serialize_credential(credential)


@router.post("/projects/{project_id}/machine-identities/{identity_id}/disable", response_model=MachineIdentityRead)
def disable_machine_identity(identity_id: uuid.UUID, project_access: ProjectAccess = Depends(require_runtime_token_management), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MachineIdentityRead:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    identity.disabled_at = identity.disabled_at or utcnow()
    identity.credential_version += 1
    write_audit_log(db, project_id=project_access.project.id, environment_id=identity.environment_id, user_id=current_user.id, action="machine_identity.disabled", metadata={"machine_identity_id": str(identity.id)})
    db.commit(); db.refresh(identity)
    return _serialize_identity(identity, db)


@router.post("/projects/{project_id}/machine-identities/{identity_id}/enable", response_model=MachineIdentityRead)
def enable_machine_identity(identity_id: uuid.UUID, project_access: ProjectAccess = Depends(require_runtime_token_management), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MachineIdentityRead:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    if identity.revoked_at:
        raise HTTPException(status_code=409, detail="Revoked identities cannot be enabled.")
    identity.disabled_at = None
    write_audit_log(db, project_id=project_access.project.id, environment_id=identity.environment_id, user_id=current_user.id, action="machine_identity.enabled", metadata={"machine_identity_id": str(identity.id)})
    db.commit(); db.refresh(identity)
    return _serialize_identity(identity, db)


@router.post("/projects/{project_id}/machine-identities/{identity_id}/unlock", response_model=MachineIdentityRead)
def unlock_machine_identity(identity_id: uuid.UUID, project_access: ProjectAccess = Depends(require_runtime_token_management), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MachineIdentityRead:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    identity.locked_until = None
    identity.failed_auth_attempts = 0
    write_audit_log(db, project_id=project_access.project.id, environment_id=identity.environment_id, user_id=current_user.id, action="machine_identity.unlocked", metadata={"machine_identity_id": str(identity.id)})
    db.commit(); db.refresh(identity)
    return _serialize_identity(identity, db)


@router.get("/projects/{project_id}/machine-identities/{identity_id}/auth-history", response_model=list[MachineAuthEventRead])
def list_machine_auth_history(identity_id: uuid.UUID, project_access: ProjectAccess = Depends(require_runtime_token_management), db: Session = Depends(get_db)) -> list[MachineAuthEventRead]:
    identity = _get_identity_or_404(db, project_id=project_access.project.id, identity_id=identity_id)
    events = db.scalars(select(MachineIdentityAuthEvent).where(MachineIdentityAuthEvent.identity_id == identity.id).order_by(MachineIdentityAuthEvent.created_at.desc()).limit(200)).all()
    return [MachineAuthEventRead.model_validate(event, from_attributes=True) for event in events]


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
    credential = get_machine_credential_by_client_id(db, client_id=payload.client_id)
    identity = db.get(MachineIdentity, credential.identity_id) if credential else None
    if identity is None:
        identity = get_machine_identity_by_client_id(db, client_id=payload.client_id)
    client_ip = _client_ip(request)
    secret_valid = bool(
        identity
        and (
            verify_machine_client_secret(plaintext=payload.client_secret, stored_hash=credential.client_secret_hash)
            if credential
            else verify_machine_client_secret(plaintext=payload.client_secret, stored_hash=identity.client_secret_hash)
        )
    )
    credential_valid = (
        is_machine_credential_active(credential)
        if credential is not None
        else identity is not None
        and (
            identity.credential_expires_at is None
            or as_utc(identity.credential_expires_at) > utcnow()
        )
    )
    identity_valid = bool(identity and is_machine_identity_active(identity))
    ip_valid = bool(identity and is_client_ip_allowed(client_ip=client_ip, trusted_cidrs=list(identity.trusted_cidrs or [])))
    success = secret_valid and credential_valid and identity_valid and ip_valid
    if not success:
        reason = "unknown_client_id" if identity is None else "invalid_secret" if not secret_valid else "inactive_credential" if not credential_valid else "identity_locked_or_inactive" if not identity_valid else "untrusted_ip"
        if identity is not None and reason == "invalid_secret":
            identity.failed_auth_attempts += 1
            if identity.failed_auth_attempts >= settings.machine_auth_max_failed_attempts:
                identity.locked_until = utcnow() + timedelta(seconds=settings.machine_auth_lockout_seconds)
                reason = "locked_after_failures"
        db.add(MachineIdentityAuthEvent(identity_id=identity.id if identity else None, credential_id=credential.id if credential else None, client_id=payload.client_id, client_ip=client_ip, success=0, reason=reason, created_at=utcnow()))
        if identity is not None and identity.project_id is not None:
            write_audit_log(db, project_id=identity.project_id, environment_id=identity.environment_id, user_id=None, action="machine_identity.authentication_failed", metadata={"machine_identity_id": str(identity.id), "client_id": payload.client_id, "client_ip": client_ip, "reason": reason, "failed_attempts": identity.failed_auth_attempts})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid machine credentials.")

    try:
        issued = issue_machine_access_token(identity, credential)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid machine credentials.",
        ) from exc
    identity.last_authenticated_at = utcnow()
    identity.failed_auth_attempts = 0
    identity.locked_until = None
    if credential is not None:
        credential.last_authenticated_at = identity.last_authenticated_at
    db.add(MachineIdentityAuthEvent(identity_id=identity.id, credential_id=credential.id if credential else None, client_id=payload.client_id, client_ip=client_ip, success=1, reason="authenticated", created_at=identity.last_authenticated_at))
    if identity.project_id is not None:
        write_audit_log(
            db,
            project_id=identity.project_id,
            environment_id=identity.environment_id,
            user_id=None,
            action="machine_identity.authenticated",
            metadata={"machine_identity_id": str(identity.id), "client_id": payload.client_id, "credential_id": str(credential.id) if credential else None},
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
    project_id: uuid.UUID | None = None,
    environment_id: uuid.UUID | None = None,
    path: str = "/",
    recursive: bool = True,
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

    selected_project_id = project_id or identity.project_id
    selected_environment_id = environment_id or identity.environment_id
    if selected_project_id is None or selected_environment_id is None:
        raise HTTPException(status_code=422, detail="Organization identities must select a project and environment.")
    project = db.get(Project, selected_project_id)
    if project is None or not (
        identity.project_id == project.id
        or (identity.organization_id is not None and identity.organization_id == project.organization_id)
    ):
        raise HTTPException(status_code=403, detail="Machine identity cannot access this project.")
    environment = get_project_environment_or_404(db, project=project, environment_id=selected_environment_id)
    latest_rows = get_latest_secret_rows(db, environment_id=environment.id, path=path, recursive=recursive)
    uses_rbac = project is not None and subject_has_assignments(
        db, project=project, machine_identity_id=identity.id
    )
    if identity.organization_id is not None and not uses_rbac:
        raise HTTPException(status_code=403, detail="Organization identities require an assigned role for this project.")
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
                environment_id=environment.id,
                path=row.path,
            ).allowed
        )
    ]
    requested_scope_allowed = not uses_rbac or evaluate_permission(
        db,
        project=project,
        machine_identity_id=identity.id,
        resource="secrets",
        action="read",
        environment_id=environment.id,
        path=path,
    ).allowed
    if uses_rbac and not scoped_rows and not requested_scope_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Machine identity has no matching permission to read secrets.",
        )
    try:
        secrets, _versions = build_secret_payload(
            db,
            project_id=project.id,
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
        project_id=project.id,
        environment_id=environment.id,
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
        project_id=project.id,
        environment_id=environment.id,
        secrets=secrets,
        generated_at=now,
    )
