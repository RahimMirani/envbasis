from __future__ import annotations

from app.api.deps import ProjectAccess
from app.api.routes.webhooks import (
    create_webhook,
    delete_webhook,
    list_supported_events,
    list_webhooks,
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

    with session_factory() as db:
        webhooks = list_webhooks(
            project_access=access,
            db=db,
        )

    assert [str(webhook.id) for webhook in webhooks] == [str(created.id)]

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
