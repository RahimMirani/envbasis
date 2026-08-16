from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_runtime_token_management
from app.db.session import get_db
from app.models.provider_credential import ProviderCredential
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
    delete_provider_credential,
    list_provider_credentials,
    upsert_provider_credential,
)

router = APIRouter(prefix="/projects")


def _serialize(credential: ProviderCredential) -> ProviderCredentialRead:
    return ProviderCredentialRead(
        id=credential.id,
        project_id=credential.project_id,
        environment_id=credential.environment_id,
        provider=credential.provider,  # type: ignore[arg-type]
        key_last4=credential.key_last4,
        updated_by=credential.updated_by,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


@router.get(
    "/{project_id}/environments/{environment_id}/provider-credentials",
    response_model=ProviderCredentialListResponse,
)
def list_environment_provider_credentials(
    environment_id: uuid.UUID,
    response: Response,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    db: Session = Depends(get_db),
) -> ProviderCredentialListResponse:
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    credentials = list_provider_credentials(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
    )
    _no_store(response)
    return ProviderCredentialListResponse(credentials=[_serialize(item) for item in credentials])


@router.put(
    "/{project_id}/environments/{environment_id}/provider-credentials",
    response_model=ProviderCredentialRead,
)
def upsert_environment_provider_credential(
    environment_id: uuid.UUID,
    payload: ProviderCredentialUpsert,
    response: Response,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProviderCredentialRead:
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    try:
        credential = upsert_provider_credential(
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
        metadata={
            "provider": credential.provider,
            "key_last4": credential.key_last4,
            "provider_credential_id": str(credential.id),
        },
    )
    db.commit()
    db.refresh(credential)
    _no_store(response)
    return _serialize(credential)


@router.delete(
    "/{project_id}/environments/{environment_id}/provider-credentials/{provider}",
    response_model=MessageResponse,
)
def delete_environment_provider_credential(
    environment_id: uuid.UUID,
    provider: str,
    project_access: ProjectAccess = Depends(require_runtime_token_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )
    deleted = delete_provider_credential(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        provider=provider,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider credential not found.",
        )
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
