from __future__ import annotations

from datetime import datetime, timedelta, timezone
import socket

from fastapi import HTTPException
import pytest
from sqlalchemy import select

import app.api.routes.webhooks as webhook_routes
import app.services.webhooks as webhook_service
from app.core.config import settings
from app.api.deps import ProjectAccess
from app.api.routes.webhooks import (
    create_webhook,
    delete_webhook,
    list_supported_events,
    list_webhook_delivery_history,
    list_webhooks,
    redeliver_webhook,
    test_webhook as trigger_webhook_test,
)
from app.models.webhook import Webhook
from app.schemas.webhook import WebhookCreate
from app.services.crypto import decrypt_text
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_delivery_attempt import WebhookDeliveryAttempt


@pytest.fixture(autouse=True)
def enable_webhooks_for_webhook_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "webhooks_enabled", True)


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def _allow_test_destination(monkeypatch) -> None:
    monkeypatch.setattr(webhook_routes, "validate_webhook_destination", lambda _url: None)


def test_webhook_create_list_delete_and_list_events(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    _allow_test_destination(monkeypatch)
    owner = seeder.user("owner-webhooks@example.com")
    project = seeder.project(owner, name="webhook-project")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_webhook(
            payload=WebhookCreate(
                url="https://example.com/hooks/envbasis",
                events=["secret.created", "runtime_token.revoked"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert str(created.url) == "https://example.com/hooks/envbasis"
    assert created.events == ["secret.created", "runtime_token.revoked"]
    assert len(created.signing_secret) == 64
    assert created.latest_delivery is None

    with session_factory() as db:
        webhooks = list_webhooks(
            project_access=access,
            db=db,
        )

    assert [str(webhook.id) for webhook in webhooks] == [str(created.id)]
    assert webhooks[0].latest_delivery is None

    supported_events = list_supported_events(_project_access=access)
    assert supported_events == sorted(supported_events)
    assert "secret.created" in supported_events
    assert "*" in supported_events

    with session_factory() as db:
        response = delete_webhook(
            webhook_id=created.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert response.detail == "Webhook deleted."

    with session_factory() as db:
        webhooks = list_webhooks(
            project_access=access,
            db=db,
        )

    assert webhooks == []
    assert seeder.audit_actions(project) == ["webhook.created", "webhook.deleted"]


def test_webhook_signing_secret_is_stored_encrypted(session_factory, seeder, monkeypatch) -> None:
    _allow_test_destination(monkeypatch)
    owner = seeder.user("owner-webhook-crypto@example.com")
    project = seeder.project(owner, name="webhook-crypto")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_webhook(
            payload=WebhookCreate(
                url="https://example.com/hooks/crypto",
                events=["secret.created"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    plaintext = created.signing_secret
    assert len(plaintext) == 64

    # Read the raw ciphertext column directly in a fresh session so we bypass
    # the plaintext cache on the object that created the row.
    with session_factory() as db:
        stored_ciphertext = db.scalar(
            select(Webhook.signing_secret_ciphertext).where(Webhook.id == created.id)
        )

    assert isinstance(stored_ciphertext, (bytes, bytearray))
    assert plaintext.encode("utf-8") not in stored_ciphertext
    assert decrypt_text(stored_ciphertext) == plaintext

    # Loading the model through ORM decrypts transparently via the property.
    with session_factory() as db:
        reloaded = db.scalar(select(Webhook).where(Webhook.id == created.id))
        assert reloaded is not None
        assert reloaded.signing_secret == plaintext


def test_webhook_test_delivery_history_and_latest_status(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    owner = seeder.user("owner-webhook-tests@example.com")
    project = seeder.project(owner, name="webhook-tests")
    access = _owner_access(project)

    _allow_test_destination(monkeypatch)
    monkeypatch.setattr(
        webhook_service,
        "deliver_webhook_request",
        lambda **_kwargs: webhook_service.DeliveryAttemptResult(
            status="success",
            response_status=204,
            error_message=None,
        ),
    )

    with session_factory() as db:
        created = create_webhook(
            payload=WebhookCreate(
                url="https://example.com/hooks/testable",
                events=["secret.created"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        delivery = trigger_webhook_test(
            webhook_id=created.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert delivery.delivery_type == "test"
    assert delivery.event == webhook_service.WEBHOOK_TEST_EVENT
    assert delivery.status == "queued"
    assert delivery.response_status is None

    with session_factory() as db:
        assert webhook_service.process_due_webhook_deliveries(db) == 1
        db.commit()

    with session_factory() as db:
        webhooks = list_webhooks(
            project_access=access,
            db=db,
        )
        deliveries = list_webhook_delivery_history(
            webhook_id=created.id,
            limit=10,
            project_access=access,
            db=db,
        )

    assert len(deliveries) == 1
    assert deliveries[0].id == delivery.id
    assert deliveries[0].status == "success"
    assert deliveries[0].response_status == 204
    assert deliveries[0].attempt_count == 1
    assert webhooks[0].latest_delivery is not None
    assert webhooks[0].latest_delivery.id == delivery.id
    assert seeder.audit_actions(project) == ["webhook.created", "webhook.test_sent"]


def _public_dns(_host, port, *, type):
    assert port in {80, 443}
    assert type == socket.SOCK_STREAM
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private_dns(_host, port, *, type):
    assert type == socket.SOCK_STREAM
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port))]


def test_webhook_destination_validation_blocks_ssrf_and_requires_production_https(
    monkeypatch,
) -> None:
    destination = webhook_service.resolve_webhook_destination(
        "https://hooks.example.test/events?source=envbasis",
        require_https=True,
        resolver=_public_dns,
    )
    assert destination.addresses == ("93.184.216.34",)
    assert destination.request_target == "/events?source=envbasis"

    with pytest.raises(webhook_service.WebhookDestinationError, match="HTTPS"):
        webhook_service.resolve_webhook_destination(
            "http://hooks.example.test/events",
            require_https=True,
            resolver=_public_dns,
        )

    for url in (
        "https://127.0.0.1/hook",
        "https://10.0.0.7/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/hook",
    ):
        with pytest.raises(webhook_service.WebhookDestinationError):
            webhook_service.resolve_webhook_destination(url, require_https=True)

    with pytest.raises(webhook_service.WebhookDestinationError, match="private"):
        webhook_service.resolve_webhook_destination(
            "https://rebind.example.test/hook",
            require_https=True,
            resolver=_private_dns,
        )

    with pytest.raises(webhook_service.WebhookDestinationError, match="metadata"):
        webhook_service.resolve_webhook_destination(
            "https://metadata.google.internal/computeMetadata/v1",
            require_https=True,
            resolver=_public_dns,
        )


def test_create_webhook_rejects_an_unsafe_destination(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-unsafe-webhook@example.com")
    project = seeder.project(owner, name="unsafe-webhook")

    with session_factory() as db, pytest.raises(HTTPException) as exc_info:
        create_webhook(
            payload=WebhookCreate(
                url="https://169.254.169.254/latest/meta-data",
                events=["secret.created"],
            ),
            project_access=_owner_access(project),
            current_user=owner,
            db=db,
        )

    assert exc_info.value.status_code == 422


def test_webhook_redirect_is_not_followed(monkeypatch) -> None:
    requests: list[str] = []

    class FakeResponse:
        status = 302
        reason = "Found"

        def read(self, _limit):
            return b""

    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, _method, target, **_kwargs):
            requests.append(target)

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(
        webhook_service,
        "resolve_webhook_destination",
        lambda _url: webhook_service.ResolvedWebhookDestination(
            url="https://hooks.example.test/start",
            scheme="https",
            hostname="hooks.example.test",
            port=443,
            request_target="/start",
            host_header="hooks.example.test",
            addresses=("93.184.216.34",),
        ),
    )
    monkeypatch.setattr(webhook_service, "_PinnedHTTPSConnection", FakeConnection)

    result = webhook_service.deliver_webhook_request(
        url="https://hooks.example.test/start",
        signing_secret="secret",
        payload_bytes=b"{}",
        event="secret.created",
        delivery_id="delivery-id",
    )

    assert result.status == "http_error"
    assert result.response_status == 302
    assert result.retryable is False
    assert requests == ["/start"]


def test_durable_webhook_queue_retries_with_exponential_backoff(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    owner = seeder.user("owner-webhook-retry@example.com")
    project = seeder.project(owner, name="webhook-retry")
    _allow_test_destination(monkeypatch)
    monkeypatch.setattr(webhook_service.settings, "webhook_retry_base_seconds", 10)
    monkeypatch.setattr(webhook_service.settings, "webhook_retry_max_seconds", 60)

    results = iter(
        [
            webhook_service.DeliveryAttemptResult(
                "network_error", None, "temporary timeout", retryable=True
            ),
            webhook_service.DeliveryAttemptResult("success", 204, None),
        ]
    )
    delivered_ids: list[str] = []

    def fake_delivery(**kwargs):
        delivered_ids.append(kwargs["delivery_id"])
        return next(results)

    monkeypatch.setattr(webhook_service, "deliver_webhook_request", fake_delivery)

    with session_factory() as db:
        created = create_webhook(
            payload=WebhookCreate(
                url="https://hooks.example.test/retry",
                events=["secret.created"],
            ),
            project_access=_owner_access(project),
            current_user=owner,
            db=db,
        )

    queued_at = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    with session_factory() as db:
        delivery = webhook_service.enqueue_webhook_delivery(
            db,
            webhook_id=created.id,
            event="secret.created",
            delivery_type="event",
            project_id=project.id,
            environment_id=None,
            actor_user_id=owner.id,
            metadata={"key": "DATABASE_URL"},
        )
        delivery.next_attempt_at = queued_at
        delivery_id = delivery.id
        db.commit()

    with session_factory() as db:
        assert webhook_service.process_due_webhook_deliveries(db, now=queued_at) == 1
        db.commit()

    with session_factory() as db:
        delivery = db.get(WebhookDelivery, delivery_id)
        assert delivery is not None
        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.next_attempt_at is not None
        assert delivery.next_attempt_at.replace(tzinfo=timezone.utc) == queued_at + timedelta(seconds=10)

    with session_factory() as db:
        assert (
            webhook_service.process_due_webhook_deliveries(
                db,
                now=queued_at + timedelta(seconds=9),
            )
            == 0
        )

    with session_factory() as db:
        assert (
            webhook_service.process_due_webhook_deliveries(
                db,
                now=queued_at + timedelta(seconds=10),
            )
            == 1
        )
        db.commit()

    with session_factory() as db:
        delivery = db.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))
        assert delivery is not None
        assert delivery.status == "success"
        assert delivery.attempt_count == 2
        assert delivery.completed_at is not None
        assert delivery.next_attempt_at is None
        attempts = list(
            db.scalars(
                select(WebhookDeliveryAttempt)
                .where(WebhookDeliveryAttempt.delivery_id == delivery_id)
                .order_by(WebhookDeliveryAttempt.attempt_number)
            ).all()
        )
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert [attempt.status for attempt in attempts] == ["network_error", "success"]
        assert attempts[0].next_retry_at is not None
        assert attempts[1].next_retry_at is None

    assert delivered_ids == [str(delivery_id), str(delivery_id)]


def test_webhook_enqueue_is_idempotent_for_same_event_key(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    owner = seeder.user("owner-webhook-idempotency@example.com")
    project = seeder.project(owner, name="webhook-idempotency")
    _allow_test_destination(monkeypatch)

    with session_factory() as db:
        webhook = create_webhook(
            payload=WebhookCreate(
                url="https://hooks.example.test/idempotent",
                events=["secret.created"],
            ),
            project_access=_owner_access(project),
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        first = webhook_service.enqueue_webhook_delivery(
            db,
            webhook_id=webhook.id,
            event="secret.created",
            delivery_type="event",
            project_id=project.id,
            environment_id=None,
            actor_user_id=owner.id,
            metadata={"key": "API_KEY"},
            idempotency_key="audit-event:123",
        )
        second = webhook_service.enqueue_webhook_delivery(
            db,
            webhook_id=webhook.id,
            event="secret.created",
            delivery_type="event",
            project_id=project.id,
            environment_id=None,
            actor_user_id=owner.id,
            metadata={"key": "API_KEY"},
            idempotency_key="audit-event:123",
        )
        assert first.id == second.id
        db.commit()

    with session_factory() as db:
        rows = list(db.scalars(select(WebhookDelivery)).all())
        assert len(rows) == 1
        assert rows[0].idempotency_key == "audit-event:123"


def test_manual_redelivery_reuses_delivery_and_preserves_attempt_history(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    owner = seeder.user("owner-webhook-redelivery@example.com")
    project = seeder.project(owner, name="webhook-redelivery")
    access = _owner_access(project)
    _allow_test_destination(monkeypatch)
    results = iter(
        [
            webhook_service.DeliveryAttemptResult("http_error", 400, "Bad Request"),
            webhook_service.DeliveryAttemptResult("success", 202, None),
        ]
    )
    monkeypatch.setattr(
        webhook_service,
        "deliver_webhook_request",
        lambda **_kwargs: next(results),
    )

    with session_factory() as db:
        webhook = create_webhook(
            payload=WebhookCreate(
                url="https://hooks.example.test/redeliver",
                events=["secret.created"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        queued = trigger_webhook_test(
            webhook_id=webhook.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db, pytest.raises(HTTPException) as exc_info:
        redeliver_webhook(
            webhook_id=webhook.id,
            delivery_id=queued.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert exc_info.value.status_code == 409

    with session_factory() as db:
        assert webhook_service.process_due_webhook_deliveries(db) == 1
        db.commit()

    with session_factory() as db:
        redelivered = redeliver_webhook(
            webhook_id=webhook.id,
            delivery_id=queued.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert redelivered.id == queued.id
    assert redelivered.status == "queued"
    assert redelivered.attempt_count == 1

    with session_factory() as db:
        assert webhook_service.process_due_webhook_deliveries(db) == 1
        db.commit()

    with session_factory() as db:
        deliveries = list_webhook_delivery_history(
            webhook_id=webhook.id,
            limit=10,
            project_access=access,
            db=db,
        )
    assert len(deliveries) == 1
    assert deliveries[0].id == queued.id
    assert deliveries[0].status == "success"
    assert deliveries[0].response_status == 202
    assert [attempt.attempt_number for attempt in deliveries[0].attempts] == [1, 2]
    assert [attempt.status for attempt in deliveries[0].attempts] == ["http_error", "success"]
    assert seeder.audit_actions(project) == [
        "webhook.created",
        "webhook.test_sent",
        "webhook.redelivery_requested",
    ]
