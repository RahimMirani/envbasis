from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_project_owner
from app.db.session import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.schemas.common import MessageResponse
from app.schemas.webhook import SUPPORTED_EVENTS, WebhookCreate, WebhookRead
from app.services.audit import write_audit_log
from app.services.webhooks import is_missing_webhooks_table

router = APIRouter(prefix="/projects")


@router.post(
    "/{project_id}/webhooks",
    response_model=WebhookRead,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook(
    payload: WebhookCreate,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Webhook:
    try:
        payload.validate_events()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    url = str(payload.url)
    signing_secret = secrets.token_hex(32)

    webhook = Webhook(
        project_id=project_access.project.id,
        url=url,
        events=payload.events,
        signing_secret=signing_secret,
        created_by=current_user.id,
    )
    db.add(webhook)
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        if is_missing_webhooks_table(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhooks are unavailable until the latest database migration is applied.",
            ) from exc
        raise
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="webhook.created",
        metadata={"webhook_id": str(webhook.id), "url": url, "events": payload.events},
    )
    db.commit()
    db.refresh(webhook)
    return webhook


@router.get("/{project_id}/webhooks", response_model=list[WebhookRead])
def list_webhooks(
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> list[Webhook]:
    try:
        return list(
            db.scalars(
                select(Webhook)
                .where(Webhook.project_id == project_access.project.id)
                .order_by(Webhook.created_at.asc())
            ).all()
        )
    except Exception as exc:
        db.rollback()
        if is_missing_webhooks_table(exc):
            return []
        raise


@router.get("/{project_id}/webhooks/events", response_model=list[str])
def list_supported_events(
    _project_access: ProjectAccess = Depends(require_project_owner),
) -> list[str]:
    return sorted(SUPPORTED_EVENTS)


@router.delete("/{project_id}/webhooks/{webhook_id}", response_model=MessageResponse)
def delete_webhook(
    webhook_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    try:
        webhook = db.scalar(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.project_id == project_access.project.id,
            )
        )
    except Exception as exc:
        db.rollback()
        if is_missing_webhooks_table(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhooks are unavailable until the latest database migration is applied.",
            ) from exc
        raise
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="webhook.deleted",
        metadata={"webhook_id": str(webhook.id), "url": webhook.url},
    )
    db.delete(webhook)
    db.commit()
    return MessageResponse(detail="Webhook deleted.")
