from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, ROLE_OWNER, get_current_user, get_project_access, require_project_owner
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.runtime_token import RuntimeToken
from app.models.runtime_token_share import RuntimeTokenShare
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.runtime_token import (
    RuntimeTokenCreateRequest,
    RuntimeTokenCreateResponse,
    RuntimeTokenNameRequest,
    RuntimeTokenRead,
)
from app.schemas.runtime_token_share import (
    RuntimeTokenRevealResponse,
    RuntimeTokenShareRead,
    RuntimeTokenShareRequest,
)
from app.services.audit import write_audit_log
from app.services.crypto import decrypt_text, encrypt_text
from app.services.environments import get_project_environment_or_404
from app.services.runtime_tokens import (
    generate_runtime_token,
    hash_runtime_token,
)
from app.services.webhooks import dispatch_webhooks, get_webhooks_for_event

router = APIRouter()


def _serialize_runtime_token(token: RuntimeToken) -> RuntimeTokenRead:
    return RuntimeTokenRead.model_validate(token)


def _ensure_shareable_runtime_token(token: RuntimeToken) -> None:
    now = datetime.now(timezone.utc)
    if token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoked runtime tokens cannot be shared or revealed.",
        )
    if token.expires_at is not None and token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Expired runtime tokens cannot be shared or revealed.",
        )
    if token.encrypted_token is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This runtime token cannot be shared or revealed. Create a new token first.",
        )


def _get_active_runtime_token_by_name_or_404(
    db: Session,
    *,
    project_id: uuid.UUID,
    name: str,
) -> RuntimeToken:
    token = db.scalar(
        select(RuntimeToken).where(
            RuntimeToken.project_id == project_id,
            RuntimeToken.name == name,
            RuntimeToken.revoked_at.is_(None),
        )
    )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active runtime token not found for this project.",
        )
    return token


def _user_can_access_runtime_token(
    db: Session,
    *,
    token: RuntimeToken,
    current_user: User,
) -> bool:
    project = db.get(Project, token.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if project.owner_id == current_user.id:
        return True

    return db.scalar(
        select(RuntimeTokenShare).where(
            RuntimeTokenShare.runtime_token_id == token.id,
            RuntimeTokenShare.user_id == current_user.id,
        )
    ) is not None


@router.post(
    "/projects/{project_id}/environments/{environment_id}/runtime-tokens",
    response_model=RuntimeTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_runtime_token(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: RuntimeTokenCreateRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuntimeTokenCreateResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    environment = get_project_environment_or_404(
        db,
        project=project_access.project,
        environment_id=environment_id,
    )

    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Runtime token name cannot be empty.",
        )
    existing_token = db.scalar(
        select(RuntimeToken).where(
            RuntimeToken.project_id == project_access.project.id,
            RuntimeToken.name == name,
            RuntimeToken.revoked_at.is_(None),
        )
    )
    if existing_token is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active runtime token with this name already exists in the project.",
        )

    if payload.expires_at is not None and payload.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Runtime token expiry must be in the future.",
        )

    plaintext_token = generate_runtime_token()
    token = RuntimeToken(
        project_id=project_access.project.id,
        environment_id=environment.id,
        token_hash=hash_runtime_token(plaintext_token),
        encrypted_token=encrypt_text(plaintext_token),
        name=name,
        expires_at=payload.expires_at,
        created_by=current_user.id,
    )
    db.add(token)
    db.flush()
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="runtime_token.created",
        metadata={"token_id": str(token.id), "name": token.name},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="runtime_token.created")
    db.commit()
    db.refresh(token)
    dispatch_webhooks(webhook_targets, event="runtime_token.created", project_id=project_access.project.id, environment_id=environment.id, actor_user_id=current_user.id, metadata={"token_id": str(token.id), "name": token.name})
    return RuntimeTokenCreateResponse(
        id=token.id,
        project_id=token.project_id,
        environment_id=token.environment_id,
        name=token.name,
        expires_at=token.expires_at,
        created_by=token.created_by,
        revoked_at=token.revoked_at,
        last_used_at=token.last_used_at,
        plaintext_token=plaintext_token,
    )


@router.get("/projects/{project_id}/runtime-tokens", response_model=list[RuntimeTokenRead])
def list_runtime_tokens(
    project_id: uuid.UUID,
    project_access: ProjectAccess = Depends(get_project_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RuntimeTokenRead]:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    if project_access.role == ROLE_OWNER:
        tokens = db.scalars(
            select(RuntimeToken)
            .where(RuntimeToken.project_id == project_access.project.id)
            .order_by(RuntimeToken.name.asc())
        ).all()
    else:
        tokens = db.scalars(
            select(RuntimeToken)
            .join(RuntimeTokenShare, RuntimeTokenShare.runtime_token_id == RuntimeToken.id)
            .where(
                RuntimeToken.project_id == project_access.project.id,
                RuntimeTokenShare.user_id == current_user.id,
            )
            .order_by(RuntimeToken.name.asc())
        ).all()
    return [_serialize_runtime_token(token) for token in tokens]


@router.post("/runtime-tokens/{token_id}/share", response_model=RuntimeTokenShareRead, status_code=status.HTTP_201_CREATED)
def share_runtime_token(
    token_id: uuid.UUID,
    payload: RuntimeTokenShareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuntimeTokenShareRead:
    token = db.get(RuntimeToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime token not found.",
        )

    project = db.get(Project, token.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can share runtime tokens.",
        )

    _ensure_shareable_runtime_token(token)

    recipient_email = payload.email.strip().lower()
    recipient = db.scalar(select(User).where(User.email == recipient_email))
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient user not found.",
        )

    if recipient.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project owners already have access to this runtime token.",
        )

    # Recipient must already be part of the project.
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == recipient.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Runtime tokens can only be shared with project members.",
        )

    existing_share = db.scalar(
        select(RuntimeTokenShare).where(
            RuntimeTokenShare.runtime_token_id == token.id,
            RuntimeTokenShare.user_id == recipient.id,
        )
    )
    if existing_share is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runtime token is already shared with this member.",
        )

    share = RuntimeTokenShare(
        runtime_token_id=token.id,
        user_id=recipient.id,
        shared_by=current_user.id,
    )
    db.add(share)
    db.flush()
    write_audit_log(
        db,
        project_id=project.id,
        environment_id=token.environment_id,
        user_id=current_user.id,
        action="runtime_token.shared",
        metadata={"token_id": str(token.id), "member_email": recipient.email},
    )
    db.commit()
    db.refresh(share)
    return RuntimeTokenShareRead(
        id=share.id,
        runtime_token_id=share.runtime_token_id,
        user_id=share.user_id,
        email=recipient.email,
        shared_by=share.shared_by,
        created_at=share.created_at,
    )


@router.get("/runtime-tokens/{token_id}/shares", response_model=list[RuntimeTokenShareRead])
def list_runtime_token_shares(
    token_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RuntimeTokenShareRead]:
    token = db.get(RuntimeToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime token not found.",
        )

    project = db.get(Project, token.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can view runtime token shares.",
        )

    rows = db.execute(
        select(RuntimeTokenShare, User.email)
        .join(User, User.id == RuntimeTokenShare.user_id)
        .where(RuntimeTokenShare.runtime_token_id == token.id)
        .order_by(RuntimeTokenShare.created_at.asc())
    ).all()
    return [
        RuntimeTokenShareRead(
            id=share.id,
            runtime_token_id=share.runtime_token_id,
            user_id=share.user_id,
            email=email,
            shared_by=share.shared_by,
            created_at=share.created_at,
        )
        for share, email in rows
    ]


@router.post(
    "/projects/{project_id}/runtime-tokens/reveal-by-name",
    response_model=RuntimeTokenRevealResponse,
)
def reveal_runtime_token_by_name(
    project_id: uuid.UUID,
    payload: RuntimeTokenNameRequest,
    response: Response,
    project_access: ProjectAccess = Depends(get_project_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuntimeTokenRevealResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    name = payload.name.strip()
    token = _get_active_runtime_token_by_name_or_404(
        db,
        project_id=project_access.project.id,
        name=name,
    )

    if not _user_can_access_runtime_token(db, token=token, current_user=current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this runtime token.",
        )

    _ensure_shareable_runtime_token(token)

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    plaintext_token = decrypt_text(token.encrypted_token)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=token.environment_id,
        user_id=current_user.id,
        action="runtime_token.revealed",
        metadata={"token_id": str(token.id), "name": token.name, "lookup": "name"},
    )
    db.commit()
    return RuntimeTokenRevealResponse(token_id=token.id, plaintext_token=plaintext_token)


@router.post(
    "/projects/{project_id}/runtime-tokens/revoke-by-name",
    response_model=MessageResponse,
)
def revoke_runtime_token_by_name(
    project_id: uuid.UUID,
    payload: RuntimeTokenNameRequest,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    name = payload.name.strip()
    token = _get_active_runtime_token_by_name_or_404(
        db,
        project_id=project_access.project.id,
        name=name,
    )

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=token.environment_id,
        user_id=current_user.id,
        action="runtime_token.revoked",
        metadata={"token_id": str(token.id), "name": token.name, "lookup": "name"},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project_access.project.id, action="runtime_token.revoked")
    _wh_meta = {"token_id": str(token.id), "name": token.name}
    _wh_project_id = project_access.project.id
    _wh_env_id = token.environment_id
    db.delete(token)
    db.commit()
    dispatch_webhooks(webhook_targets, event="runtime_token.revoked", project_id=_wh_project_id, environment_id=_wh_env_id, actor_user_id=current_user.id, metadata=_wh_meta)
    return MessageResponse(detail="Runtime token revoked.")


@router.post("/runtime-tokens/{token_id}/reveal", response_model=RuntimeTokenRevealResponse)
def reveal_runtime_token(
    token_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RuntimeTokenRevealResponse:
    token = db.get(RuntimeToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime token not found.",
        )

    project = db.get(Project, token.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if not _user_can_access_runtime_token(db, token=token, current_user=current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this runtime token.",
        )

    _ensure_shareable_runtime_token(token)

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    plaintext_token = decrypt_text(token.encrypted_token)
    write_audit_log(
        db,
        project_id=project.id,
        environment_id=token.environment_id,
        user_id=current_user.id,
        action="runtime_token.revealed",
        metadata={"token_id": str(token.id), "name": token.name},
    )
    db.commit()
    return RuntimeTokenRevealResponse(token_id=token.id, plaintext_token=plaintext_token)


@router.post("/runtime-tokens/{token_id}/revoke", response_model=MessageResponse)
def revoke_runtime_token(
    token_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    token = db.get(RuntimeToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime token not found.",
        )

    project = db.get(Project, token.project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owners can perform this action.",
        )

    write_audit_log(
        db,
        project_id=project.id,
        environment_id=token.environment_id,
        user_id=current_user.id,
        action="runtime_token.revoked",
        metadata={"token_id": str(token.id), "name": token.name},
    )
    webhook_targets = get_webhooks_for_event(db, project_id=project.id, action="runtime_token.revoked")
    _wh_meta = {"token_id": str(token.id), "name": token.name}
    _wh_env_id = token.environment_id
    db.delete(token)
    db.commit()
    dispatch_webhooks(webhook_targets, event="runtime_token.revoked", project_id=project.id, environment_id=_wh_env_id, actor_user_id=current_user.id, metadata=_wh_meta)
    return MessageResponse(detail="Runtime token revoked.")
