from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from fastapi import HTTPException
import pytest

from app.api.deps import ProjectAccess
from app.api.routes.secret_history import (
    get_secret_retention,
    list_secret_versions,
    recover_environment_secrets,
    recover_project_secrets,
    reveal_secret_version,
    rollback_secret_version,
    update_secret_retention,
)
from app.api.routes.secrets import create_secret, delete_secret, pull_secrets, update_secret
from app.models.secret import Secret
from app.schemas.secret import SecretCreateRequest, SecretUpdateRequest
from app.schemas.secret_history import RecoveryRequest, SecretRetentionUpdate


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_complete_version_history_reveal_and_rollback(session_factory, seeder) -> None:
    owner = seeder.user("history-owner@example.com")
    project = seeder.project(owner, name="history-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(
                key="TOKEN",
                value="v1-value",
                path="/api",
                description="Original",
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
        update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            path="/api",
            payload=SecretUpdateRequest(value="v2-value", description="Updated"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        history = list_secret_versions(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            path="/api",
            include_archived=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        revealed = reveal_secret_version(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            version=1,
            path="/api",
            project_access=access,
            current_user=owner,
            db=db,
        )
        rolled_back = rollback_secret_version(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            version=1,
            path="/api",
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [item.version for item in history.versions] == [2, 1]
    assert history.versions[0].updated_by_email == owner.email
    assert revealed.value == "v1-value"
    assert rolled_back.source_version == 1
    assert rolled_back.version == 3

    with session_factory() as db:
        current = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/api",
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert current.secrets == {"TOKEN": "v1-value"}


def test_retention_policy_archives_old_versions_without_destroying_history(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("retention-owner@example.com")
    project = seeder.project(owner, name="retention-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        policy = update_secret_retention(
            project_id=project.id,
            payload=SecretRetentionUpdate(
                retain_versions=2,
                retain_days=None,
                archive_deleted_after_days=None,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
        for index in range(1, 5):
            if index == 1:
                create_secret(
                    project_id=project.id,
                    environment_id=environment.id,
                    payload=SecretCreateRequest(key="TOKEN", value=f"v{index}"),
                    project_access=access,
                    current_user=owner,
                    db=db,
                )
            else:
                update_secret(
                    project_id=project.id,
                    environment_id=environment.id,
                    secret_key="TOKEN",
                    payload=SecretUpdateRequest(value=f"v{index}"),
                    project_access=access,
                    current_user=owner,
                    db=db,
                )

    assert policy.retain_versions == 2
    with session_factory() as db:
        visible = list_secret_versions(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            include_archived=False,
            project_access=access,
            current_user=owner,
            db=db,
        )
        complete = list_secret_versions(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            include_archived=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
        read_policy = get_secret_retention(project_id=project.id, project_access=access, db=db)
    assert [item.version for item in visible.versions] == [4, 3]
    assert [item.version for item in complete.versions] == [4, 3, 2, 1]
    assert all(item.archived_at is not None for item in complete.versions[2:])
    assert read_policy.retain_versions == 2


def test_environment_and_project_point_in_time_recovery(session_factory, seeder) -> None:
    owner = seeder.user("recovery-owner@example.com")
    project = seeder.project(owner, name="recovery-project")
    environment = seeder.environment(project, name="prod")
    second_environment = seeder.environment(project, name="staging")
    access = _owner_access(project)

    with session_factory() as db:
        for target in (environment, second_environment):
            create_secret(
                project_id=project.id,
                environment_id=target.id,
                payload=SecretCreateRequest(key="TOKEN", value="old", path="/api"),
                project_access=access,
                current_user=owner,
                db=db,
            )
            update_secret(
                project_id=project.id,
                environment_id=target.id,
                secret_key="TOKEN",
                path="/api",
                payload=SecretUpdateRequest(value="new"),
                project_access=access,
                current_user=owner,
                db=db,
            )
        rows = list(db.scalars(select(Secret).order_by(Secret.environment_id, Secret.version)).all())
        for row in rows:
            row.updated_at = datetime(
                2026,
                1,
                1 if row.version == 1 else 3,
                tzinfo=timezone.utc,
            )
        db.commit()

    recovery_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with session_factory() as db:
        preview = recover_environment_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=RecoveryRequest(at=recovery_time, path="/api", dry_run=True),
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert preview.changed == 1
    assert preview.items[0].action == "restore"

    with session_factory() as db:
        restored = recover_project_secrets(
            project_id=project.id,
            payload=RecoveryRequest(at=recovery_time, path="/api", dry_run=False),
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert restored.changed == 2
    assert restored.environments_changed == 2

    with session_factory() as db:
        first = pull_secrets(
            project_id=project.id,
            environment_id=environment.id,
            path="/api",
            project_access=access,
            current_user=owner,
            db=db,
        )
        second = pull_secrets(
            project_id=project.id,
            environment_id=second_environment.id,
            path="/api",
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert first.secrets["TOKEN"] == "old"
    assert second.secrets["TOKEN"] == "old"


def test_delete_secret_removes_history_and_recovery_can_hard_delete(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("history-delete-owner@example.com")
    project = seeder.project(owner, name="history-delete-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="TOKEN", value="v1"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            payload=SecretUpdateRequest(value="v2"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        delete_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db, pytest.raises(HTTPException) as missing_history:
        list_secret_versions(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="TOKEN",
            include_archived=True,
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert missing_history.value.status_code == 404
    assert seeder.secret_versions(environment) == []

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="LATER_KEY", value="after-snapshot"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        rows = list(db.scalars(select(Secret).where(Secret.key == "LATER_KEY")).all())
        for row in rows:
            row.updated_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        db.commit()

    with session_factory() as db:
        recovered = recover_environment_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=RecoveryRequest(
                at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                dry_run=False,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert recovered.changed == 1
    assert recovered.items[0].action == "delete"
    assert recovered.items[0].key == "LATER_KEY"
    assert seeder.secret_versions(environment) == []
    recovery_deletes = [
        entry
        for entry in seeder.audit_logs(project)
        if entry.action == "secret.deleted" and entry.metadata_json.get("via") == "recovery"
    ]
    assert len(recovery_deletes) == 1
    assert recovery_deletes[0].metadata_json["key"] == "LATER_KEY"
