from __future__ import annotations

from inspect import signature

from fastapi import HTTPException
import pytest

from app.api.deps import (
    ProjectAccess,
    get_project_access,
    require_secret_management,
)
from app.api.routes.secrets import (
    bulk_delete_secrets,
    create_secret,
    delete_secret,
    get_secret_stats,
    list_project_secrets,
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


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_secret_routes_apply_the_permission_contract() -> None:
    metadata_only_routes = (
        get_secret_stats,
        list_project_secrets,
        list_secrets,
    )
    secret_value_or_mutation_routes = (
        reveal_secret,
        pull_secrets,
        push_secrets,
        create_secret,
        update_secret,
        delete_secret,
        bulk_delete_secrets,
    )

    for route in metadata_only_routes:
        dependency = signature(route).parameters["project_access"].default
        assert dependency.dependency is get_project_access

    for route in secret_value_or_mutation_routes:
        dependency = signature(route).parameters["project_access"].default
        assert dependency.dependency is require_secret_management


def test_reveal_secret_requires_secret_management_permission(session_factory, seeder) -> None:
    owner = seeder.user("owner-reveal-permission@example.com")
    allowed_member = seeder.user("allowed-reveal-permission@example.com")
    restricted_member = seeder.user("restricted-reveal-permission@example.com")
    non_member = seeder.user("non-member-reveal-permission@example.com")
    project = seeder.project(owner, name="reveal-permission-project")
    environment = seeder.environment(project, name="prod")
    seeder.add_member(
        project=project,
        user=allowed_member,
        can_push_pull_secrets=True,
        invited_by=owner,
    )
    seeder.add_member(
        project=project,
        user=restricted_member,
        can_push_pull_secrets=False,
        invited_by=owner,
    )

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="OPENAI_API_KEY", value="sk-private"),
            project_access=_owner_access(project),
            current_user=owner,
            db=db,
        )

    route_dependency = signature(reveal_secret).parameters["project_access"].default
    assert route_dependency.dependency is require_secret_management

    for user in (owner, allowed_member):
        with session_factory() as db:
            access = get_project_access(project.id, current_user=user, db=db)
            assert require_secret_management(access) is access
            reveal_response = reveal_secret(
                project_id=project.id,
                environment_id=environment.id,
                secret_key="OPENAI_API_KEY",
                project_access=access,
                current_user=user,
                db=db,
            )
            assert reveal_response.value == "sk-private"

    with session_factory() as db:
        restricted_access = get_project_access(
            project.id,
            current_user=restricted_member,
            db=db,
        )
        metadata_response = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=restricted_access,
            current_user=restricted_member,
            db=db,
        )
        assert [secret.key for secret in metadata_response.secrets] == ["OPENAI_API_KEY"]
        assert all(not hasattr(secret, "value") for secret in metadata_response.secrets)

        with pytest.raises(HTTPException) as restricted_error:
            require_secret_management(restricted_access)
        assert restricted_error.value.status_code == 403
        assert restricted_error.value.detail == (
            "You do not have permission to manage this project's secrets."
        )

    with session_factory() as db:
        with pytest.raises(HTTPException) as non_member_error:
            get_project_access(project.id, current_user=non_member, db=db)
        assert non_member_error.value.status_code == 403
        assert non_member_error.value.detail == "You do not have access to this project."


def test_secret_push_list_pull_and_reveal_round_trip(session_factory, seeder) -> None:
    owner = seeder.user("owner@example.com")
    project = seeder.project(owner, name="secret-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

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


def test_secret_pull_enforces_path_and_all_requested_tags(session_factory, seeder) -> None:
    owner = seeder.user("owner-selectors@example.com")
    project = seeder.project(owner, name="selector-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(secrets={"ROOT_KEY": "root"}),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(
                secrets={"BACKEND_KEY": "backend"},
                path="backend/",
                tags=["API", "shared", "api"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        root = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        backend = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/backend/",
            tag=["api", "shared"],
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        missing_tag = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/backend",
            tag=["production"],
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        listed = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert root.secrets == {"ROOT_KEY": "root"}
    assert backend.secrets == {"BACKEND_KEY": "backend"}
    assert missing_tag.secrets == {}
    metadata = {secret.key: secret for secret in listed.secrets}
    assert metadata["BACKEND_KEY"].path == "/backend"
    assert metadata["BACKEND_KEY"].tags == ["api", "shared"]


def test_secret_update_preserves_selectors_and_rejects_path_traversal(session_factory, seeder) -> None:
    owner = seeder.user("owner-selector-update@example.com")
    project = seeder.project(owner, name="selector-update-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(
                key="WORKER_KEY",
                value="v1",
                path="/worker",
                tags=["jobs"],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        updated = update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="WORKER_KEY",
            payload=SecretUpdateRequest(value="v2"),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        selected = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/worker",
            tag=["jobs"],
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert updated.path == "/worker"
    assert updated.tags == ["jobs"]
    assert selected.secrets == {"WORKER_KEY": "v2"}

    with session_factory() as db:
        with pytest.raises(HTTPException) as invalid_path:
            pull_secrets(
                project_id=project.id,
                environment_id=environment.id,
                path="/worker/../prod",
                project_access=access,
                current_user=owner,
                db=db,
            )
    assert invalid_path.value.status_code == 422
def test_secret_create_update_and_delete_increment_versions(session_factory, seeder) -> None:
    owner = seeder.user("owner-2@example.com")
    project = seeder.project(owner, name="mutation-project")
    environment = seeder.environment(project, name="staging")
    access = _owner_access(project)

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
    access = _owner_access(project)
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
    access = _owner_access(project)

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


def test_project_secret_list_supports_environment_scope_search_and_pagination(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-project-list@example.com")
    project = seeder.project(owner, name="project-list")
    prod = seeder.environment(project, name="prod")
    staging = seeder.environment(project, name="staging")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=prod.id,
            payload=SecretCreateRequest(key="ALPHA_KEY", value="one"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_secret(
            project_id=project.id,
            environment_id=staging.id,
            payload=SecretCreateRequest(key="BRAVO_KEY", value="two"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_secret(
            project_id=project.id,
            environment_id=prod.id,
            payload=SecretCreateRequest(key="CHARLIE_KEY", value="three"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        first_page = list_project_secrets(
            project_id=project.id,
            key=None,
            environment_id=None,
            limit=2,
            cursor=None,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [item.key for item in first_page.secrets] == ["ALPHA_KEY", "BRAVO_KEY"]
    assert first_page.next_cursor == "2"

    with session_factory() as db:
        second_page = list_project_secrets(
            project_id=project.id,
            key=None,
            environment_id=None,
            limit=2,
            cursor=first_page.next_cursor,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [item.key for item in second_page.secrets] == ["CHARLIE_KEY"]
    assert second_page.next_cursor is None

    with session_factory() as db:
        filtered = list_project_secrets(
            project_id=project.id,
            key="BRAVO",
            environment_id=[staging.id],
            limit=50,
            cursor=None,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [(item.key, item.environment_name) for item in filtered.secrets] == [
        ("BRAVO_KEY", "staging")
    ]
