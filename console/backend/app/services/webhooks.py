from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
from ipaddress import IPv4Address, IPv6Address, ip_address
import json
import logging
import socket
import ssl
from typing import Any, Callable, TypedDict
from urllib.parse import SplitResult, urlsplit
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import PRODUCTION_ENV_NAMES, settings
from app.db.session import SessionLocal
from app.models.webhook import Webhook
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_delivery_attempt import WebhookDeliveryAttempt

logger = logging.getLogger(__name__)

WEBHOOK_TEST_EVENT = "webhook.test"
QUEUED_DELIVERY_STATUSES = ("queued", "retrying")
RETRYABLE_HTTP_STATUSES = {408, 425, 429}
BLOCKED_METADATA_HOSTNAMES = {
    "instance-data.ec2.internal",
    "metadata.google.internal",
    "metadata.google",
    "metadata.azure.internal",
}


class WebhookTarget(TypedDict):
    webhook_id: uuid.UUID
    url: str
    signing_secret: str


@dataclass(frozen=True)
class DeliveryAttemptResult:
    status: str
    response_status: int | None
    error_message: str | None
    retryable: bool = False


@dataclass(frozen=True)
class ResolvedWebhookDestination:
    url: str
    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str
    addresses: tuple[str, ...]


class WebhookDestinationError(ValueError):
    pass


class WebhookDNSResolutionError(WebhookDestinationError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_missing_webhooks_table(exc: Exception) -> bool:
    if not isinstance(exc, ProgrammingError):
        return False
    return 'relation "webhooks" does not exist' in str(exc)


def is_missing_webhook_deliveries_table(exc: Exception) -> bool:
    if not isinstance(exc, ProgrammingError):
        return False
    message = str(exc)
    return (
        'relation "webhook_deliveries" does not exist' in message
        or 'column webhook_deliveries.payload does not exist' in message
    )


def get_webhooks_for_event(
    db: Session,
    *,
    project_id: uuid.UUID,
    action: str,
) -> list[WebhookTarget]:
    if not settings.webhooks_enabled:
        return []
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
        logger.warning("Skipping webhook lookup because the webhooks table is unavailable.")
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


def _is_forbidden_address(address: IPv4Address | IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    )


def _parse_webhook_url(url: str, *, require_https: bool) -> SplitResult:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise WebhookDestinationError("Webhook URL contains an invalid port.") from exc

    if parsed.scheme not in {"http", "https"}:
        raise WebhookDestinationError("Webhook URL must use HTTP or HTTPS.")
    if require_https and parsed.scheme != "https":
        raise WebhookDestinationError("Webhook URL must use HTTPS in production.")
    if not parsed.hostname:
        raise WebhookDestinationError("Webhook URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise WebhookDestinationError("Webhook URL cannot contain user credentials.")
    if parsed.fragment:
        raise WebhookDestinationError("Webhook URL cannot contain a fragment.")
    if port is not None and not 1 <= port <= 65535:
        raise WebhookDestinationError("Webhook URL contains an invalid port.")
    return parsed


def _resolve_hostname(
    hostname: str,
    port: int,
    *,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> tuple[str, ...]:
    try:
        literal = ip_address(hostname)
    except ValueError:
        try:
            results = resolver(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise WebhookDNSResolutionError(
                "Webhook hostname could not be resolved."
            ) from exc
        addresses: list[str] = []
        for result in results:
            raw_address = result[4][0]
            if raw_address not in addresses:
                addresses.append(raw_address)
        if not addresses:
            raise WebhookDNSResolutionError("Webhook hostname did not resolve to an IP address.")
    else:
        addresses = [str(literal)]

    normalized: list[str] = []
    for raw_address in addresses:
        try:
            address = ip_address(raw_address)
        except ValueError as exc:
            raise WebhookDNSResolutionError(
                "Webhook hostname resolved to an invalid IP address."
            ) from exc
        if _is_forbidden_address(address):
            raise WebhookDestinationError(
                "Webhook destinations cannot resolve to loopback, private, link-local, "
                "reserved, multicast, or unspecified addresses."
            )
        normalized.append(str(address))
    return tuple(normalized)


def resolve_webhook_destination(
    url: str,
    *,
    require_https: bool | None = None,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> ResolvedWebhookDestination:
    enforce_https = (
        settings.app_env.lower() in PRODUCTION_ENV_NAMES
        if require_https is None
        else require_https
    )
    parsed = _parse_webhook_url(url, require_https=enforce_https)
    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    if hostname.rstrip(".") in BLOCKED_METADATA_HOSTNAMES:
        raise WebhookDestinationError("Cloud metadata webhook destinations are forbidden.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = _resolve_hostname(hostname, port, resolver=resolver)
    request_target = parsed.path or "/"
    if parsed.query:
        request_target += f"?{parsed.query}"
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if parsed.scheme == "https" else 80
    host_header = display_host if port == default_port else f"{display_host}:{port}"
    return ResolvedWebhookDestination(
        url=url,
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        request_target=request_target,
        host_header=host_header,
        addresses=addresses,
    )


def validate_webhook_destination(url: str) -> None:
    # DNS is intentionally resolved during creation and again immediately before
    # every connection. The connection itself is pinned to that checked address.
    resolve_webhook_destination(url)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, address: str, port: int, *, timeout: int) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._resolved_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int, *, timeout: int) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._resolved_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def build_webhook_payload(
    *,
    event: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
    delivery_id: uuid.UUID | None = None,
) -> tuple[str, bytes]:
    effective_delivery_id = delivery_id or uuid.uuid4()
    payload = {
        "id": str(effective_delivery_id),
        "event": event,
        "project_id": str(project_id),
        "environment_id": str(environment_id) if environment_id else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "metadata": metadata or {},
        "fired_at": utcnow().isoformat(),
    }
    return str(effective_delivery_id), json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _truncate_error_message(message: str | None) -> str | None:
    return message[:1024] if message else None


def _is_retryable_http_status(response_status: int) -> bool:
    return response_status in RETRYABLE_HTTP_STATUSES or response_status >= 500


def deliver_webhook_request(
    *,
    url: str,
    signing_secret: str,
    payload_bytes: bytes,
    event: str,
    delivery_id: str,
    attempt_number: int = 1,
) -> DeliveryAttemptResult:
    try:
        destination = resolve_webhook_destination(url)
    except WebhookDNSResolutionError as exc:
        return DeliveryAttemptResult(
            status="network_error",
            response_status=None,
            error_message=_truncate_error_message(str(exc)),
            retryable=True,
        )
    except WebhookDestinationError as exc:
        return DeliveryAttemptResult(
            status="blocked",
            response_status=None,
            error_message=_truncate_error_message(str(exc)),
            retryable=False,
        )

    signature = "sha256=" + hmac.new(
        signing_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(payload_bytes)),
        "Host": destination.host_header,
        "X-Envbasis-Event": event,
        "X-Envbasis-Delivery": delivery_id,
        "X-Envbasis-Attempt": str(attempt_number),
        "X-Envbasis-Signature": signature,
        "User-Agent": "EnvBasis-Webhooks/1.0",
    }

    last_error: Exception | None = None
    for address in destination.addresses:
        connection: http.client.HTTPConnection
        if destination.scheme == "https":
            connection = _PinnedHTTPSConnection(
                destination.hostname,
                address,
                destination.port,
                timeout=settings.webhook_request_timeout_seconds,
            )
        else:
            connection = _PinnedHTTPConnection(
                destination.hostname,
                address,
                destination.port,
                timeout=settings.webhook_request_timeout_seconds,
            )
        try:
            connection.request(
                "POST",
                destination.request_target,
                body=payload_bytes,
                headers=headers,
            )
            response = connection.getresponse()
            response.read(1024)
            if 200 <= response.status < 300:
                return DeliveryAttemptResult("success", response.status, None)
            # Redirects are intentionally not followed. Following an attacker-controlled
            # redirect could bypass destination validation and reach an internal service.
            return DeliveryAttemptResult(
                status="http_error",
                response_status=response.status,
                error_message=_truncate_error_message(f"HTTP {response.status} {response.reason}"),
                retryable=_is_retryable_http_status(response.status),
            )
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()

    logger.warning("Webhook delivery failed: event=%s url=%s error=%s", event, url, last_error)
    return DeliveryAttemptResult(
        status="network_error",
        response_status=None,
        error_message=_truncate_error_message(str(last_error or "Webhook connection failed.")),
        retryable=True,
    )


def enqueue_webhook_delivery(
    db: Session,
    *,
    webhook_id: uuid.UUID,
    event: str,
    delivery_type: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
    idempotency_key: str | None = None,
) -> WebhookDelivery:
    if idempotency_key is not None:
        normalized_idempotency_key = idempotency_key.strip()
        if not normalized_idempotency_key:
            raise ValueError("Webhook idempotency key cannot be empty.")
        if len(normalized_idempotency_key) > 255:
            raise ValueError("Webhook idempotency key cannot exceed 255 characters.")
        existing = db.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.webhook_id == webhook_id,
                WebhookDelivery.idempotency_key == normalized_idempotency_key,
            )
        )
        if existing is not None:
            return existing
    else:
        normalized_idempotency_key = None

    row_id = uuid.uuid4()
    normalized_idempotency_key = normalized_idempotency_key or f"delivery:{row_id}"
    _delivery_id, payload_bytes = build_webhook_payload(
        event=event,
        project_id=project_id,
        environment_id=environment_id,
        actor_user_id=actor_user_id,
        metadata=metadata,
        delivery_id=row_id,
    )
    delivery = WebhookDelivery(
        id=row_id,
        webhook_id=webhook_id,
        idempotency_key=normalized_idempotency_key,
        event=event,
        delivery_type=delivery_type,
        status="queued",
        response_status=None,
        error_message=None,
        payload=payload_bytes.decode("utf-8"),
        attempt_count=0,
        max_attempts=settings.webhook_max_attempts,
        next_attempt_at=utcnow(),
        last_attempt_at=None,
        triggered_by=actor_user_id,
        completed_at=None,
    )
    db.add(delivery)
    db.flush()
    return delivery


def list_webhook_deliveries(
    db: Session,
    *,
    webhook_id: uuid.UUID,
    limit: int = 10,
    offset: int = 0,
) -> list[WebhookDelivery]:
    return list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook_id)
            .order_by(WebhookDelivery.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


def count_webhook_deliveries(db: Session, *, webhook_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(WebhookDelivery.id)).where(
                WebhookDelivery.webhook_id == webhook_id
            )
        )
        or 0
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
        if row.webhook_id not in latest_by_webhook:
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
    return enqueue_webhook_delivery(
        db,
        webhook_id=webhook.id,
        event=WEBHOOK_TEST_EVENT,
        delivery_type="test",
        project_id=webhook.project_id,
        environment_id=None,
        actor_user_id=triggered_by,
        metadata={
            "mode": "manual_test",
            "webhook_id": str(webhook.id),
            "webhook_url": webhook.url,
        },
        idempotency_key=f"test:{uuid.uuid4()}",
    )


def dispatch_webhooks(
    targets: list[WebhookTarget],
    *,
    db: Session | None = None,
    event: str,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    metadata: dict[str, Any] | None,
    event_id: uuid.UUID | str | None = None,
) -> list[WebhookDelivery]:
    if not settings.webhooks_enabled or not targets:
        return []
    effective_event_id = str(event_id or uuid.uuid4())
    event_key = "event:" + hashlib.sha256(
        f"{event}:{effective_event_id}".encode("utf-8")
    ).hexdigest()
    owns_session = db is None
    queue_db = db or SessionLocal()
    deliveries: list[WebhookDelivery] = []
    try:
        for target in targets:
            deliveries.append(
                enqueue_webhook_delivery(
                    queue_db,
                    webhook_id=target["webhook_id"],
                    event=event,
                    delivery_type="event",
                    project_id=project_id,
                    environment_id=environment_id,
                    actor_user_id=actor_user_id,
                    metadata=metadata,
                    idempotency_key=event_key,
                )
            )
        if owns_session:
            queue_db.commit()
        else:
            queue_db.flush()
    except Exception as exc:
        if owns_session:
            queue_db.rollback()
        if is_missing_webhook_deliveries_table(exc):
            if owns_session:
                logger.warning("Skipping webhook enqueue because the queue migration is unavailable.")
                return []
            # The delivery is part of the caller's transaction. Failing the
            # transaction avoids committing an event without its durable job.
            raise
        logger.exception("Failed to enqueue durable webhook deliveries.")
        raise
    finally:
        if owns_session:
            queue_db.close()
    return deliveries


def redeliver_webhook_delivery(
    db: Session,
    *,
    delivery: WebhookDelivery,
) -> WebhookDelivery:
    if delivery.status in QUEUED_DELIVERY_STATUSES:
        raise ValueError("Webhook delivery is already queued or retrying.")

    delivery.status = "queued"
    delivery.response_status = None
    delivery.error_message = None
    delivery.next_attempt_at = utcnow()
    delivery.completed_at = None
    # A manual redelivery starts a fresh automatic-retry budget while keeping
    # attempt numbers monotonic for the logical delivery.
    delivery.max_attempts = delivery.attempt_count + settings.webhook_max_attempts
    db.flush()
    return delivery


def _retry_delay_seconds(attempt_count: int) -> int:
    delay = settings.webhook_retry_base_seconds * (2 ** max(attempt_count - 1, 0))
    return min(delay, settings.webhook_retry_max_seconds)


def process_due_webhook_deliveries(
    db: Session,
    *,
    limit: int | None = None,
    now: datetime | None = None,
) -> int:
    if not settings.webhooks_enabled:
        return 0
    effective_now = now or utcnow()
    batch_size = limit or settings.webhook_worker_batch_size
    jobs = list(
        db.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(QUEUED_DELIVERY_STATUSES),
                or_(
                    WebhookDelivery.next_attempt_at.is_(None),
                    WebhookDelivery.next_attempt_at <= effective_now,
                ),
            )
            .order_by(WebhookDelivery.next_attempt_at.asc(), WebhookDelivery.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        ).all()
    )

    for delivery in jobs:
        webhook = db.get(Webhook, delivery.webhook_id)
        delivery.attempt_count += 1
        attempt_number = delivery.attempt_count
        delivery.last_attempt_at = effective_now
        delivery.next_attempt_at = None

        if webhook is None or not webhook.is_active:
            delivery.status = "canceled"
            delivery.error_message = "Webhook is missing or inactive."
            delivery.completed_at = effective_now
            db.add(
                WebhookDeliveryAttempt(
                    delivery=delivery,
                    attempt_number=attempt_number,
                    status="canceled",
                    response_status=None,
                    error_message=delivery.error_message,
                    started_at=effective_now,
                    completed_at=effective_now,
                    next_retry_at=None,
                )
            )
            continue

        attempt_started_at = utcnow()
        result = deliver_webhook_request(
            url=webhook.url,
            signing_secret=webhook.signing_secret,
            payload_bytes=delivery.payload.encode("utf-8"),
            event=delivery.event,
            delivery_id=str(delivery.id),
            attempt_number=attempt_number,
        )
        attempt_completed_at = utcnow()
        delivery.response_status = result.response_status
        delivery.error_message = result.error_message
        if result.status == "success":
            delivery.status = "success"
            delivery.completed_at = effective_now
        elif result.retryable and delivery.attempt_count < delivery.max_attempts:
            delivery.status = "retrying"
            delivery.next_attempt_at = effective_now + timedelta(
                seconds=_retry_delay_seconds(delivery.attempt_count)
            )
            delivery.completed_at = None
        else:
            delivery.status = result.status
            delivery.completed_at = attempt_completed_at

        db.add(
            WebhookDeliveryAttempt(
                delivery=delivery,
                attempt_number=attempt_number,
                status=result.status,
                response_status=result.response_status,
                error_message=result.error_message,
                started_at=attempt_started_at,
                completed_at=attempt_completed_at,
                next_retry_at=delivery.next_attempt_at,
            )
        )

    db.flush()
    return len(jobs)
