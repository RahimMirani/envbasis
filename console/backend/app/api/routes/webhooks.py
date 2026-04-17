from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, get_current_user, require_project_owner
from app.db.session import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.schemas.common import MessageResponse
from app.schemas.webhook import (
    SUPPORTED_EVENTS,
    WebhookCreate,
    WebhookDeliveryRead,
    WebhookRead,
)
from app.services.audit import write_audit_log
from app.services.webhooks import (
    get_latest_deliveries_for_webhooks,
    is_missing_webhook_deliveries_table,
    is_missing_webhooks_table,
    list_webhook_deliveries,
    send_test_webhook,
)

router = APIRouter(prefix="/projects")


def _serialize_delivery(delivery) -> WebhookDeliveryRead:
    return WebhookDeliveryRead.model_validate(delivery)


def _serialize_webhook(webhook: Webhook, latest_delivery=None) -> WebhookRead:
    return WebhookRead.model_validate(webhook).model_copy(
        update={
            "latest_delivery": _serialize_delivery(latest_delivery) if latest_delivery else None,
        }
    )


def _get_project_webhook_or_404(
    db: Session,
    *,
    project_id: uuid.UUID,
    webhook_id: uuid.UUID,
) -> Webhook:
    try:
        webhook = db.scalar(
            select(Webhook).where(
                Webhook.id == webhook_id,
                Webhook.project_id == project_id,
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

    return webhook


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
) -> WebhookRead:
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
        created_by=current_user.id,
    )
    webhook.set_signing_secret(signing_secret)
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
    return _serialize_webhook(webhook)


@router.get("/{project_id}/webhooks", response_model=list[WebhookRead])
def list_webhooks(
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> list[WebhookRead]:
    try:
        webhooks = list(
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

    latest_by_webhook = {}
    if webhooks:
        try:
            latest_by_webhook = get_latest_deliveries_for_webhooks(
                db,
                webhook_ids=[webhook.id for webhook in webhooks],
            )
        except Exception as exc:
            db.rollback()
            if not is_missing_webhook_deliveries_table(exc):
                raise

    return [_serialize_webhook(webhook, latest_by_webhook.get(webhook.id)) for webhook in webhooks]


@router.get("/{project_id}/webhooks/events", response_model=list[str])
def list_supported_events(
    _project_access: ProjectAccess = Depends(require_project_owner),
) -> list[str]:
    return sorted(SUPPORTED_EVENTS)


@router.get(
    "/{project_id}/webhooks/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryRead],
)
def list_webhook_delivery_history(
    webhook_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    project_access: ProjectAccess = Depends(require_project_owner),
    db: Session = Depends(get_db),
) -> list[WebhookDeliveryRead]:
    _get_project_webhook_or_404(
        db,
        project_id=project_access.project.id,
        webhook_id=webhook_id,
    )

    try:
        deliveries = list_webhook_deliveries(db, webhook_id=webhook_id, limit=limit)
    except Exception as exc:
        db.rollback()
        if is_missing_webhook_deliveries_table(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook delivery tracking is unavailable until the latest database migration is applied.",
            ) from exc
        raise

    return [_serialize_delivery(delivery) for delivery in deliveries]


@router.post(
    "/{project_id}/webhooks/{webhook_id}/test",
    response_model=WebhookDeliveryRead,
)
def test_webhook(
    webhook_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WebhookDeliveryRead:
    webhook = _get_project_webhook_or_404(
        db,
        project_id=project_access.project.id,
        webhook_id=webhook_id,
    )

    try:
        delivery = send_test_webhook(
            db,
            webhook=webhook,
            triggered_by=current_user.id,
        )
    except Exception as exc:
        db.rollback()
        if is_missing_webhook_deliveries_table(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook delivery tracking is unavailable until the latest database migration is applied.",
            ) from exc
        raise

    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="webhook.test_sent",
        metadata={
            "webhook_id": str(webhook.id),
            "url": webhook.url,
            "status": delivery.status,
            "response_status": delivery.response_status,
        },
    )
    db.commit()
    db.refresh(delivery)
    return _serialize_delivery(delivery)


@router.delete("/{project_id}/webhooks/{webhook_id}", response_model=MessageResponse)
def delete_webhook(
    webhook_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_project_owner),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    webhook = _get_project_webhook_or_404(
        db,
        project_id=project_access.project.id,
        webhook_id=webhook_id,
    )

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
