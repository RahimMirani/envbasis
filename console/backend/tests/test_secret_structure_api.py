from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import ProjectAccess
from app.api.routes.secret_structure import (
    create_project_secret_tag,
    create_secret_folder,
    delete_project_secret_tag,
    delete_secret_folder,
    list_project_secret_tags,
    list_secret_folders,
    update_project_secret_tag,
)
from app.api.routes.secrets import create_secret, list_secrets, pull_secrets, reveal_secret, update_secret
from app.schemas.secret import SecretCreateRequest, SecretUpdateRequest
from app.schemas.secret_structure import (
    ProjectSecretTagCreate,
    ProjectSecretTagUpdate,
    SecretFolderCreate,
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


def test_nested_folders_are_created_listed_and_protected_from_unsafe_delete(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("folder-owner@example.com")
    project = seeder.project(owner, name="folder-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_secret_folder(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretFolderCreate(path="//backend//payments/", description="Payment service"),
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert created.path == "/backend/payments"
    assert created.parent_path == "/backend"

    with session_factory() as db:
        root = list_secret_folders(
            project_id=project.id,
            environment_id=environment.id,
            path="/",
            recursive=False,
            project_access=access,
            current_user=owner,
            db=db,
        )
        recursive = list_secret_folders(
            project_id=project.id,
            environment_id=environment.id,
            path="/",
            recursive=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert [folder.path for folder in root.folders] == ["/backend"]
    assert [folder.path for folder in recursive.folders] == ["/backend", "/backend/payments"]

    with session_factory() as db:
        with pytest.raises(HTTPException) as child_conflict:
            delete_secret_folder(
                project_id=project.id,
                environment_id=environment.id,
                path="/backend",
                recursive=False,
                project_access=access,
                current_user=owner,
                db=db,
            )
    assert child_conflict.value.status_code == 409

    with session_factory() as db:
        response = delete_secret_folder(
            project_id=project.id,
            environment_id=environment.id,
            path="/backend",
            recursive=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert response.status_code == 204


def test_same_key_can_exist_in_multiple_paths_and_requires_disambiguation(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("path-owner@example.com")
    project = seeder.project(owner, name="path-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="TOKEN", value="root", path="/"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="TOKEN", value="worker", path="/worker"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        listed = list_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/",
            recursive=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        pulled = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/",
            recursive=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        worker = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            path="/worker",
            project_access=access,
            current_user=owner,
            db=db,
        )
        with pytest.raises(HTTPException) as ambiguous:
            reveal_secret(
                project_id=project.id,
                environment_id=environment.id,
                secret_key="TOKEN",
                project_access=access,
                current_user=owner,
                db=db,
            )

    assert [(item.path, item.key) for item in listed.secrets] == [("/", "TOKEN"), ("/worker", "TOKEN")]
    assert pulled.secrets == {"TOKEN": "root"}
    assert worker.value == "worker"
    assert ambiguous.value.status_code == 409


def test_metadata_and_project_tags_are_versioned_and_catalogued(session_factory, seeder) -> None:
    owner = seeder.user("metadata-owner@example.com")
    project = seeder.project(owner, name="metadata-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(
                key="DATABASE_URL",
                value="postgres://example",
                path="/backend",
                tags=["Critical", "database"],
                description="Primary database",
                owner="platform@example.com",
                service="api",
                rotation_interval_days=30,
                custom_metadata={"region": "us-west-2"},
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert created.tags == ["critical", "database"]
    assert created.description == "Primary database"

    with session_factory() as db:
        updated = update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="DATABASE_URL",
            path="/backend",
            payload=SecretUpdateRequest(value="postgres://new", description="Rotated database"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        tags = list_project_secret_tags(
            project_id=project.id,
            project_access=access,
            db=db,
        )
    assert updated.version == 2
    assert updated.description == "Rotated database"
    assert updated.owner == "platform@example.com"
    assert updated.custom_metadata == {"region": "us-west-2"}
    assert [tag.name for tag in tags] == ["critical", "database"]

    with session_factory() as db:
        extra = create_project_secret_tag(
            project_id=project.id,
            payload=ProjectSecretTagCreate(name="payments", color="#3366ff"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        changed = update_project_secret_tag(
            project_id=project.id,
            tag_id=extra.id,
            payload=ProjectSecretTagUpdate(color="#000000", description="Payments team"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        response = delete_project_secret_tag(
            project_id=project.id,
            tag_id=extra.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert changed.description == "Payments team"
    assert response.status_code == 204


def test_folder_path_traversal_is_rejected() -> None:
    with pytest.raises(ValueError):
        SecretFolderCreate(path="/backend/../admin")
