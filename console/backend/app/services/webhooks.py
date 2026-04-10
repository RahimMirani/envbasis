from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import threading
import urllib.error
import urllib.request
import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.webhook import Webhook
from app.models.webhook_delivery import WebhookDelivery

logger = logging.getLogger(__name__)

WEBHOOK_TEST_EVENT = "webhook.test"


class WebhookTarget(TypedDict):
    webhook_id: uuid.UUID
    url: str
    signing_secret: str


@dataclass
class DeliveryAttemptResult:
    status: str
    response_status: int | None
    error_message: str | None


def is_missing_webhooks_table(exc: Exception) -> bool:
    if not isinstance(exc, ProgrammingError):
        return False

    return 'relation "webhooks" does not exist' in str(exc)


def is_missing_webhook_deliveries_table(exc: Exception) -> bool:
    if not isinstance(exc, ProgrammingError):
        return False

    return 'relation "webhook_deliveries" does not exist' in str(exc)


def get_webhooks_for_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    action: str,
) -> list[WebhookTarget]:
    try:
        rows = db.scalars(
            select(Webhook).where(
                Webhook.project_id == project_id,
                Webhook.is_active.is_(True),
            )
        ).all()
    except ProgrammingError as exc:
        if not is_missing_webhooks_table(exc):
            raise

        logger.warning("Skipping webhook lookup because the webhooks table is not available yet.")
        db.rollback()
        return []

    targets: list[WebhookTarget] = []
    for webhook in rows:
        events: list[str] = webhook.events or []
        if "*" in events or action in events:
            targets.append(
                {
                    "webhook_id": webhook.id,
                    "url": webhook.url,
                    "signing_secret": webhook.signing_secret,
                }
            )
    return targets


def build_webhook_payload(
    *,
    event: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
) -> tuple[str, bytes]:
    delivery_id = str(uuid.uuid4())
    payload = {
        "id": delivery_id,
        "event": event,
        "project_id": str(project_id),
        "environment_id": str(environment_id) if environment_id else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "metadata": metadata or {},
        "fired_at": datetime.now(timezone.utc).isoformat(),
    }
    return delivery_id, json.dumps(payload).encode("utf-8")


def _truncate_error_message(message: str | None) -> str | None:
    if not message:
        return None

    return message[:1024]


def deliver_webhook_request(
    *,
    url: str,
    signing_secret: str,
    payload_bytes: bytes,
    event: str,
    delivery_id: str,
) -> DeliveryAttemptResult:
    mac = hmac.new(signing_secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    signature = "sha256=" + mac.hexdigest()

    req = urllib.request.Request(
        url=url,
        data=payload_bytes,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Envbasis-Event": event,
            "X-Envbasis-Delivery": delivery_id,
            "X-Envbasis-Signature": signature,
            "User-Agent": "EnvBasis-Webhooks/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.debug("Webhook delivered: event=%s url=%s status=%s", event, url, resp.status)
            return DeliveryAttemptResult(
                status="success",
                response_status=resp.status,
                error_message=None,
            )
    except urllib.error.HTTPError as exc:
        logger.warning("Webhook HTTP error: event=%s url=%s status=%s", event, url, exc.code)
        return DeliveryAttemptResult(
            status="http_error",
            response_status=exc.code,
            error_message=_truncate_error_message(str(exc.reason or exc)),
        )
    except Exception as exc:  # pragma: no cover - exercised in tests via monkeypatch
        logger.warning("Webhook delivery failed: event=%s url=%s error=%s", event, url, exc)
        return DeliveryAttemptResult(
            status="network_error",
            response_status=None,
            error_message=_truncate_error_message(str(exc)),
        )


def create_delivery_record(
    db: Session,
    *,
    webhook_id: uuid.UUID,
    event: str,
    delivery_type: str,
    triggered_by: uuid.UUID | None,
    result: DeliveryAttemptResult,
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        webhook_id=webhook_id,
        event=event,
        delivery_type=delivery_type,
        status=result.status,
        response_status=result.response_status,
        error_message=result.error_message,
        triggered_by=triggered_by,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(delivery)
    db.flush()
    return delivery


def list_webhook_deliveries(
    db: Session,
    *,
    webhook_id: uuid.UUID,
    limit: int = 10,
) -> list[WebhookDelivery]:
    return list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(limit)
        ).all()
    )


def get_latest_deliveries_for_webhooks(
    db: Session,
    *,
    webhook_ids: list[uuid.UUID],
) -> dict[uuid.UUID, WebhookDelivery]:
    if not webhook_ids:
        return {}

    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id.in_(webhook_ids))
        .order_by(WebhookDelivery.created_at.desc())
    ).all()

    latest_by_webhook: dict[uuid.UUID, WebhookDelivery] = {}
    for row in rows:
        if row.webhook_id in latest_by_webhook:
            continue
        latest_by_webhook[row.webhook_id] = row
        if len(latest_by_webhook) == len(webhook_ids):
            break

    return latest_by_webhook


def send_test_webhook(
    db: Session,
    *,
    webhook: Webhook,
    triggered_by: uuid.UUID | None,
) -> WebhookDelivery:
    delivery_id, payload_bytes = build_webhook_payload(
        event=WEBHOOK_TEST_EVENT,
        project_id=webhook.project_id,
        environment_id=None,
        actor_user_id=triggered_by,
        metadata={
            "mode": "manual_test",
            "webhook_id": str(webhook.id),
            "webhook_url": webhook.url,
        },
    )
    result = deliver_webhook_request(
        url=webhook.url,
        signing_secret=webhook.signing_secret,
        payload_bytes=payload_bytes,
        event=WEBHOOK_TEST_EVENT,
        delivery_id=delivery_id,
    )
    return create_delivery_record(
        db,
        webhook_id=webhook.id,
        event=WEBHOOK_TEST_EVENT,
        delivery_type="test",
        triggered_by=triggered_by,
        result=result,
    )


def dispatch_webhooks(
    targets: list[WebhookTarget],
    *,
    event: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
) -> None:
    if not targets:
        return

    delivery_id, payload_bytes = build_webhook_payload(
        event=event,
        project_id=project_id,
        environment_id=environment_id,
        actor_user_id=actor_user_id,
        metadata=metadata,
    )

    for target in targets:
        t = threading.Thread(
            target=_deliver_and_record,
            args=(
                target["webhook_id"],
                target["url"],
                target["signing_secret"],
                payload_bytes,
                event,
                actor_user_id,
                delivery_id,
            ),
            daemon=True,
        )
        t.start()


def _deliver_and_record(
    webhook_id: uuid.UUID,
    url: str,
    signing_secret: str,
    payload_bytes: bytes,
    event: str,
    actor_user_id: uuid.UUID | None,
    delivery_id: str,
) -> None:
    result = deliver_webhook_request(
        url=url,
        signing_secret=signing_secret,
        payload_bytes=payload_bytes,
        event=event,
        delivery_id=delivery_id,
    )

    db = SessionLocal()
    try:
        create_delivery_record(
            db,
            webhook_id=webhook_id,
            event=event,
            delivery_type="event",
            triggered_by=actor_user_id,
            result=result,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if is_missing_webhook_deliveries_table(exc):
            logger.warning(
                "Skipping webhook delivery persistence because the webhook_deliveries table is not available yet."
            )
            return

        logger.warning(
            "Failed to persist webhook delivery result: webhook_id=%s event=%s error=%s",
            webhook_id,
            event,
            exc,
        )
    finally:
        db.close()
