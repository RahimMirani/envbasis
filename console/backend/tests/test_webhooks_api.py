from __future__ import annotations

import app.services.webhooks as webhook_service
from app.api.deps import ProjectAccess
from app.api.routes.webhooks import (
    create_webhook,
    delete_webhook,
    list_supported_events,
    list_webhook_delivery_history,
    list_webhooks,
    test_webhook as trigger_webhook_test,
)
from app.schemas.webhook import WebhookCreate


def test_webhook_create_list_delete_and_list_events(session_factory, seeder) -> None:
    owner = seeder.user("owner-webhooks@example.com")
    project = seeder.project(owner, name="webhook-project")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

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


def test_webhook_test_delivery_history_and_latest_status(
    session_factory,
    seeder,
    monkeypatch,
) -> None:
    owner = seeder.user("owner-webhook-tests@example.com")
    project = seeder.project(owner, name="webhook-tests")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

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
    assert delivery.status == "success"
    assert delivery.response_status == 204

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
    assert webhooks[0].latest_delivery is not None
    assert webhooks[0].latest_delivery.id == delivery.id
    assert seeder.audit_actions(project) == ["webhook.created", "webhook.test_sent"]
