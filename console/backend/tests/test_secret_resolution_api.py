from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import ProjectAccess
from app.api.routes.secret_imports import (
    create_secret_import,
    delete_secret_import,
    list_secret_imports,
    update_secret_import,
)
from app.api.routes.secrets import create_secret, pull_secrets
from app.schemas.secret import SecretCreateRequest
from app.schemas.secret_import import SecretImportCreate, SecretImportUpdate


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_references_support_resolved_and_unresolved_modes(session_factory, seeder) -> None:
    owner = seeder.user("reference-owner@example.com")
    project = seeder.project(owner, name="reference-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="DATABASE_HOST", value="db.internal", path="/backend"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        created = create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(
                key="DATABASE_URL",
                value="postgres://${DATABASE_HOST}/app",
                path="/backend",
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert created.is_reference is True

    with session_factory() as db:
        resolved = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/backend",
            resolve_references=True,
            include_imports=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        unresolved = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/backend",
            resolve_references=False,
            include_imports=True,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert resolved.secrets["DATABASE_URL"] == "postgres://db.internal/app"
    reference_item = next(item for item in resolved.items if item.key == "DATABASE_URL")
    assert reference_item.value_kind == "reference"
    assert reference_item.referenced_keys == ["DATABASE_HOST"]
    assert reference_item.resolved is True
    assert unresolved.secrets["DATABASE_URL"] == "postgres://${DATABASE_HOST}/app"
    assert unresolved.resolution_mode == "unresolved"


def test_reference_cycles_are_rejected_when_created(session_factory, seeder) -> None:
    owner = seeder.user("cycle-owner@example.com")
    project = seeder.project(owner, name="cycle-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="A", value="${B}"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        with pytest.raises(HTTPException) as cycle:
            create_secret(
                project_id=project.id,
                environment_id=environment.id,
                payload=SecretCreateRequest(key="B", value="${A}"),
                project_access=access,
                current_user=owner,
                db=db,
            )
    assert cycle.value.status_code == 422
    assert cycle.value.detail["code"] == "secret_reference_cycle"
    assert cycle.value.detail["cycle"] == ["A", "B", "A"]


def test_imports_are_deterministic_and_local_values_win(session_factory, seeder) -> None:
    owner = seeder.user("import-owner@example.com")
    project = seeder.project(owner, name="import-project")
    shared = seeder.environment(project, name="shared")
    fallback = seeder.environment(project, name="fallback")
    production = seeder.environment(project, name="production")
    access = _owner_access(project)

    with session_factory() as db:
        for environment, values in [
            (shared, {"TOKEN": "shared", "SHARED_ONLY": "yes"}),
            (fallback, {"TOKEN": "fallback", "REGION": "us-east-1"}),
            (production, {"TOKEN": "local"}),
        ]:
            for key, value in values.items():
                create_secret(
                    project_id=project.id,
                    environment_id=environment.id,
                    payload=SecretCreateRequest(key=key, value=value, path="/service"),
                    project_access=access,
                    current_user=owner,
                    db=db,
                )

    with session_factory() as db:
        primary = create_secret_import(
            project_id=project.id,
            payload=SecretImportCreate(
                target_environment_id=production.id,
                target_path="/service",
                source_environment_id=shared.id,
                source_path="/service",
                priority=100,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_secret_import(
            project_id=project.id,
            payload=SecretImportCreate(
                target_environment_id=production.id,
                target_path="/service",
                source_environment_id=fallback.id,
                source_path="/service",
                priority=10,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        response = pull_secrets(
            project_id=project.id,
            environment_id=production.id,
            path="/service",
            resolve_references=True,
            include_imports=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        no_imports = pull_secrets(
            project_id=project.id,
            environment_id=production.id,
            path="/service",
            resolve_references=True,
            include_imports=False,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert response.secrets == {
        "REGION": "us-east-1",
        "SHARED_ONLY": "yes",
        "TOKEN": "local",
    }
    assert next(item for item in response.items if item.key == "TOKEN").source == "local"
    assert next(item for item in response.items if item.key == "SHARED_ONLY").source == "imported"
    assert no_imports.secrets == {"TOKEN": "local"}

    with session_factory() as db:
        changed = update_secret_import(
            project_id=project.id,
            import_id=primary.id,
            payload=SecretImportUpdate(enabled=False, priority=50),
            project_access=access,
            current_user=owner,
            db=db,
        )
        listed = list_secret_imports(project_id=project.id, project_access=access, db=db)
        deleted = delete_secret_import(
            project_id=project.id,
            import_id=primary.id,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert changed.enabled is False
    assert len(listed) == 2
    assert deleted.status_code == 204


def test_missing_reference_is_reported_without_exposing_other_values(session_factory, seeder) -> None:
    owner = seeder.user("missing-owner@example.com")
    project = seeder.project(owner, name="missing-project")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)
    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="URL", value="https://${MISSING}/v1"),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        response = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            resolve_references=True,
            include_imports=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert response.secrets["URL"] == "https://${MISSING}/v1"
    assert response.resolution_errors == ["URL: Missing referenced secret: MISSING"]
