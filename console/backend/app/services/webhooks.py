from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.models.webhook import Webhook

logger = logging.getLogger(__name__)


def is_missing_webhooks_table(exc: Exception) -> bool:
    if not isinstance(exc, ProgrammingError):
        return False

    return 'relation "webhooks" does not exist' in str(exc)


def get_webhooks_for_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    action: str,
) -> list[dict[str, str]]:
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

    targets = []
    for webhook in rows:
        events: list[str] = webhook.events or []
        if "*" in events or action in events:
            targets.append({"url": webhook.url, "signing_secret": webhook.signing_secret})
    return targets


def dispatch_webhooks(
    targets: list[dict[str, str]],
    *,
    event: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
) -> None:
    if not targets:
        return

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
    payload_bytes = json.dumps(payload).encode("utf-8")

    for target in targets:
        t = threading.Thread(
            target=_deliver,
            args=(target["url"], target["signing_secret"], payload_bytes, event, delivery_id),
            daemon=True,
        )
        t.start()


def _deliver(
    url: str,
    signing_secret: str,
    payload_bytes: bytes,
    event: str,
    delivery_id: str,
) -> None:
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
    except urllib.error.HTTPError as exc:
        logger.warning("Webhook HTTP error: event=%s url=%s status=%s", event, url, exc.code)
    except Exception as exc:
        logger.warning("Webhook delivery failed: event=%s url=%s error=%s", event, url, exc)
