from __future__ import annotations

from app.api.deps import ProjectAccess
from app.api.routes.secrets import (
    bulk_delete_secrets,
    create_secret,
    delete_secret,
    list_secrets,
    pull_secrets,
    push_secrets,
    reveal_secret,
    update_secret,
)
from datetime import datetime, timedelta, timezone

from app.schemas.secret import (
    SecretBulkDeleteItem,
    SecretBulkDeleteRequest,
    SecretCreateRequest,
    SecretPushRequest,
    SecretUpdateRequest,
)


def test_secret_push_list_pull_and_reveal_round_trip(session_factory, seeder) -> None:
    owner = seeder.user("owner@example.com")
    project = seeder.project(owner, name="secret-project")
    environment = seeder.environment(project, name="prod")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

    with session_factory() as db:
        push_response = push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(
                secrets={
                    "DEBUG": "true",
                    "OPENAI_API_KEY": "sk-test",
                }
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert push_response.changed == 2
        assert push_response.unchanged == 0
        assert push_response.total_received == 2

    with session_factory() as db:
        second_push_response = push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(
                secrets={
                    "DEBUG": "true",
                    "OPENAI_API_KEY": "sk-test",
                }
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert second_push_response.changed == 0
        assert second_push_response.unchanged == 2

    with session_factory() as db:
        list_response = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    secret_items = {item.key: item for item in list_response.secrets}
    assert set(secret_items) == {"DEBUG", "OPENAI_API_KEY"}
    assert secret_items["OPENAI_API_KEY"].updated_by_email == owner.email

    with session_factory() as db:
        reveal_response = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="OPENAI_API_KEY",
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert reveal_response.value == "sk-test"
    assert reveal_response.version == 1

    with session_factory() as db:
        pull_response = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert pull_response.secrets == {
        "DEBUG": "true",
        "OPENAI_API_KEY": "sk-test",
    }
    assert pull_response.versions == {
        "DEBUG": 1,
        "OPENAI_API_KEY": 1,
    }

    versions = seeder.secret_versions(environment)
    assert [(secret.key, secret.version, secret.is_deleted) for secret in versions] == [
        ("DEBUG", 1, False),
        ("OPENAI_API_KEY", 1, False),
    ]
    assert seeder.audit_actions(project) == [
        "secrets.pushed",
        "secrets.pushed",
        "secrets.listed",
        "secret.revealed",
        "secrets.pulled",
    ]


def test_secret_create_update_and_delete_increment_versions(session_factory, seeder) -> None:
    owner = seeder.user("owner-2@example.com")
    project = seeder.project(owner, name="mutation-project")
    environment = seeder.environment(project, name="staging")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

    with session_factory() as db:
        create_response = create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="DATABASE_URL", value="postgres://initial"),
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert create_response.version == 1
        assert create_response.changed is True

    with session_factory() as db:
        update_response = update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="DATABASE_URL",
            payload=SecretUpdateRequest(value="postgres://rotated"),
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert update_response.version == 2
        assert update_response.changed is True

    with session_factory() as db:
        delete_response = delete_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="DATABASE_URL",
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert delete_response.version == 3

    with session_factory() as db:
        list_response = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

        assert list_response.secrets == []

    with session_factory() as db:
        try:
            reveal_secret(
                project_id=project.id,
                environment_id=environment.id,
                secret_key="DATABASE_URL",
                project_access=access,
                current_user=owner,
                db=db,
            )
        except Exception as exc:  # pragma: no branch
            from fastapi import HTTPException

            assert isinstance(exc, HTTPException)
            assert exc.status_code == 404
            assert exc.detail == "Secret not found."
        else:  # pragma: no cover
            raise AssertionError("Expected reveal_secret to reject deleted secrets")

    versions = seeder.secret_versions(environment)
    assert [(secret.key, secret.version, secret.is_deleted) for secret in versions] == [
        ("DATABASE_URL", 1, False),
        ("DATABASE_URL", 2, False),
        ("DATABASE_URL", 3, True),
    ]


def test_secret_expiration_can_be_set_updated_and_cleared(session_factory, seeder) -> None:
    owner = seeder.user("owner-expiry@example.com")
    project = seeder.project(owner, name="expiry-project")
    environment = seeder.environment(project, name="prod")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)
    initial_expiry = datetime.now(timezone.utc) + timedelta(days=7)
    updated_expiry = datetime.now(timezone.utc) + timedelta(days=14)

    with session_factory() as db:
        create_response = create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(
                key="API_TOKEN",
                value="secret-value",
                expires_at=initial_expiry,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert create_response.changed is True
    assert create_response.expires_at == initial_expiry

    with session_factory() as db:
        update_response = update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="API_TOKEN",
            payload=SecretUpdateRequest(value="secret-value", expires_at=updated_expiry),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert update_response.changed is True
    assert update_response.version == 2
    assert update_response.expires_at == updated_expiry

    with session_factory() as db:
        clear_response = update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="API_TOKEN",
            payload=SecretUpdateRequest(value="secret-value", expires_at=None),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert clear_response.changed is True
    assert clear_response.version == 3
    assert clear_response.expires_at is None

    with session_factory() as db:
        list_response = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
        reveal_response = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="API_TOKEN",
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert list_response.secrets[0].expires_at is None
    assert reveal_response.expires_at is None


def test_bulk_delete_secrets_marks_each_secret_deleted(session_factory, seeder) -> None:
    owner = seeder.user("owner-bulk-delete@example.com")
    project = seeder.project(owner, name="bulk-delete-project")
    environment = seeder.environment(project, name="prod")
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="FIRST_KEY", value="one"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="SECOND_KEY", value="two"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        response = bulk_delete_secrets(
            project_id=project.id,
            payload=SecretBulkDeleteRequest(
                items=[
                    SecretBulkDeleteItem(environment_id=environment.id, key="FIRST_KEY"),
                    SecretBulkDeleteItem(environment_id=environment.id, key="SECOND_KEY"),
                ]
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert response.detail == "Deleted 2 secret(s)."

    with session_factory() as db:
        list_response = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert list_response.secrets == []
