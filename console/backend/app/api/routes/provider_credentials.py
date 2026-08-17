from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ProjectAccess,
    enforce_project_permission,
    get_current_user,
    require_secret_management,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.provider_credential import (
    ProviderCredentialListResponse,
    ProviderCredentialRead,
    ProviderCredentialUpsert,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.provider_credentials import (
    SUPPORTED_PROVIDERS,
    delete_provider_credential,
    list_provider_credentials,
    upsert_provider_credential,
)

router = APIRouter()


def _forbid_machines(project_access: ProjectAccess) -> None:
    if project_access.subject_machine_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Machine identities cannot manage provider credentials.",
        )


@router.get(
    "/projects/{project_id}/environments/{environment_id}/provider-credentials",
    response_model=ProviderCredentialListResponse,
)
def list_environment_provider_credentials(
    environment_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_secret_management),
    db: Session = Depends(get_db),
) -> ProviderCredentialListResponse:
    _forbid_machines(project_access)
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="read",
        environment_id=environment.id,
        legacy_allowed=True,
    )
    rows = list_provider_credentials(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
    )
    return ProviderCredentialListResponse(
        items=[
            ProviderCredentialRead(
                provider=row.provider,  # type: ignore[arg-type]
                key_last4=row.key_last4,
                updated_at=row.updated_at,
                updated_by=row.updated_by,
            )
            for row in rows
        ]
    )


@router.put(
    "/projects/{project_id}/environments/{environment_id}/provider-credentials",
    response_model=ProviderCredentialRead,
)
def upsert_environment_provider_credential(
    environment_id: uuid.UUID,
    payload: ProviderCredentialUpsert,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderCredentialRead:
    _forbid_machines(project_access)
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        legacy_allowed=True,
    )
    try:
        row = upsert_provider_credential(
            db,
            project_id=project_access.project.id,
            environment_id=environment.id,
            provider=payload.provider,
            secret=payload.secret,
            updated_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="provider_credential.upserted",
        metadata={"provider": row.provider, "key_last4": row.key_last4},
    )
    db.commit()
    db.refresh(row)
    return ProviderCredentialRead(
        provider=row.provider,  # type: ignore[arg-type]
        key_last4=row.key_last4,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.delete(
    "/projects/{project_id}/environments/{environment_id}/provider-credentials/{provider}",
    response_model=MessageResponse,
)
def delete_environment_provider_credential(
    environment_id: uuid.UUID,
    provider: str,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    _forbid_machines(project_access)
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential not found.")
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    enforce_project_permission(
        db,
        project_access=project_access,
        resource="secrets",
        action="write",
        environment_id=environment.id,
        legacy_allowed=True,
    )
    deleted = delete_provider_credential(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        provider=provider,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential not found.")
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="provider_credential.deleted",
        metadata={"provider": provider},
    )
    db.commit()
    return MessageResponse(detail="Provider credential deleted.")
