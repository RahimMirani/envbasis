from __future__ import annotations

from inspect import signature

import pytest
from sqlalchemy import select

from app.api.deps import ProjectAccess, require_project_owner
from app.api.routes.projects import create_project, rotate_project_key
from app.api.routes.secrets import create_secret, reveal_secret, update_secret
from app.models.project_encryption_key import ProjectEncryptionKey
from app.models.secret import Secret
from app.schemas.project import ProjectCreate
from app.schemas.secret import SecretCreateRequest, SecretUpdateRequest
from app.core.config import settings
from app.services.crypto import decrypt_secret_value, encrypt_secret_value
import app.services.root_key_provider as root_key_provider


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_project_creation_provisions_the_first_wrapped_key(session_factory, seeder) -> None:
    owner = seeder.user("owner-project-provisioning@example.com")

    with session_factory() as db:
        project = create_project(
            payload=ProjectCreate(name="provisioned-encryption-project"),
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        project_key = db.scalar(
            select(ProjectEncryptionKey).where(
                ProjectEncryptionKey.project_id == project.id
            )
        )

    assert project_key is not None
    assert project_key.version == 1
    assert project_key.is_active is True
    assert project_key.wrapped_key


def test_new_secret_uses_a_wrapped_project_key_and_records_its_version(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-project-key@example.com")
    project = seeder.project(owner, name="project-key-project")
    environment = seeder.environment(project, name="prod")

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="API_KEY", value="project-secret"),
            project_access=_owner_access(project),
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        project_keys = db.scalars(
            select(ProjectEncryptionKey).where(ProjectEncryptionKey.project_id == project.id)
        ).all()
        secret = db.scalar(
            select(Secret).where(Secret.environment_id == environment.id)
        )

        assert len(project_keys) == 1
        assert project_keys[0].version == 1
        assert project_keys[0].is_active is True
        assert secret is not None
        assert secret.encryption_key_version == 1
        assert b"project-secret" not in secret.encrypted_value
        with pytest.raises(RuntimeError):
            decrypt_secret_value(secret.encrypted_value)


def test_projects_use_different_data_encryption_keys(session_factory, seeder) -> None:
    owner = seeder.user("owner-project-isolation@example.com")
    first_project = seeder.project(owner, name="first-encryption-project")
    second_project = seeder.project(owner, name="second-encryption-project")
    first_environment = seeder.environment(first_project, name="prod")
    second_environment = seeder.environment(second_project, name="prod")

    for project, environment in (
        (first_project, first_environment),
        (second_project, second_environment),
    ):
        with session_factory() as db:
            create_secret(
                project_id=project.id,
                environment_id=environment.id,
                payload=SecretCreateRequest(key="SHARED_NAME", value="same-plaintext"),
                project_access=_owner_access(project),
                current_user=owner,
                db=db,
            )

    with session_factory() as db:
        first_key = db.scalar(
            select(ProjectEncryptionKey).where(
                ProjectEncryptionKey.project_id == first_project.id
            )
        )
        second_key = db.scalar(
            select(ProjectEncryptionKey).where(
                ProjectEncryptionKey.project_id == second_project.id
            )
        )
        first_secret = db.scalar(
            select(Secret).where(Secret.environment_id == first_environment.id)
        )
        second_secret = db.scalar(
            select(Secret).where(Secret.environment_id == second_environment.id)
        )

        assert first_key is not None
        assert second_key is not None
        assert first_key.wrapped_key != second_key.wrapped_key
        assert first_secret is not None
        assert second_secret is not None
        assert first_secret.encrypted_value != second_secret.encrypted_value


def test_aws_kms_provider_generates_and_unwraps_a_project_bound_data_key(
    session_factory,
    seeder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeKmsClient:
        def __init__(self) -> None:
            self.generate_calls: list[dict] = []
            self.decrypt_calls: list[dict] = []
            self._plaintext_by_ciphertext: dict[bytes, bytes] = {}

        def generate_data_key(self, **request):
            self.generate_calls.append(request)
            plaintext = b"k" * 32
            ciphertext = f"kms:{request['EncryptionContext']['envbasis:project_id']}".encode()
            self._plaintext_by_ciphertext[ciphertext] = plaintext
            return {
                "Plaintext": plaintext,
                "CiphertextBlob": ciphertext,
                "KeyId": "arn:aws:kms:us-west-2:123456789012:key/test-key",
            }

        def decrypt(self, **request):
            self.decrypt_calls.append(request)
            return {"Plaintext": self._plaintext_by_ciphertext[bytes(request["CiphertextBlob"])]}

    fake_kms = FakeKmsClient()
    monkeypatch.setattr(settings, "secrets_root_key_provider", "aws_kms")
    monkeypatch.setattr(settings, "aws_kms_key_id", "alias/envbasis-test")
    monkeypatch.setattr(root_key_provider, "_build_aws_kms_client", lambda: fake_kms)

    owner = seeder.user("owner-aws-kms@example.com")
    project = seeder.project(owner, name="aws-kms-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="KMS_SECRET", value="kms-protected"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    # The provider recorded on the key controls future unwraps, even if the active
    # provider configuration later changes.
    monkeypatch.setattr(settings, "secrets_root_key_provider", "local")

    with session_factory() as db:
        project_key = db.scalar(
            select(ProjectEncryptionKey).where(ProjectEncryptionKey.project_id == project.id)
        )
        revealed = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="KMS_SECRET",
            project_access=access,
            current_user=owner,
            db=db,
        )

    expected_context = {
        "envbasis:purpose": "project-data-encryption-key",
        "envbasis:project_id": str(project.id),
    }
    assert project_key is not None
    assert project_key.wrapping_provider == "aws_kms"
    assert project_key.wrapping_key_id == "arn:aws:kms:us-west-2:123456789012:key/test-key"
    assert fake_kms.generate_calls[0]["EncryptionContext"] == expected_context
    assert fake_kms.decrypt_calls[0]["EncryptionContext"] == expected_context
    assert revealed.value == "kms-protected"


def test_owner_rotation_reencrypts_every_secret_version_atomically(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-key-rotation@example.com")
    project = seeder.project(owner, name="rotation-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="DATABASE_URL", value="postgres://v1"),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        update_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="DATABASE_URL",
            payload=SecretUpdateRequest(value="postgres://v2"),
            project_access=access,
            current_user=owner,
            db=db,
        )

    route_dependency = signature(rotate_project_key).parameters["project_access"].default
    assert route_dependency.dependency is require_project_owner

    with session_factory() as db:
        result = rotate_project_key(
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert result.previous_version == 1
    assert result.active_version == 2
    assert result.secrets_reencrypted == 2

    with session_factory() as db:
        keys = db.scalars(
            select(ProjectEncryptionKey)
            .where(ProjectEncryptionKey.project_id == project.id)
            .order_by(ProjectEncryptionKey.version.asc())
        ).all()
        secret_versions = db.scalars(
            select(Secret)
            .where(Secret.environment_id == environment.id)
            .order_by(Secret.version.asc())
        ).all()
        revealed = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="DATABASE_URL",
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [(key.version, key.is_active) for key in keys] == [(1, False), (2, True)]
    assert keys[0].retired_at is not None
    assert [secret.encryption_key_version for secret in secret_versions] == [2, 2]
    assert revealed.value == "postgres://v2"
    assert seeder.audit_actions(project)[-1] == "secret.revealed"
    assert "project.encryption_key.rotated" in seeder.audit_actions(project)


def test_rotation_migrates_a_legacy_root_encrypted_secret(session_factory, seeder) -> None:
    owner = seeder.user("owner-legacy-encryption@example.com")
    project = seeder.project(owner, name="legacy-encryption-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        db.add(
            Secret(
                environment_id=environment.id,
                key="LEGACY_KEY",
                encrypted_value=encrypt_secret_value("legacy-value"),
                encryption_key_version=None,
                version=1,
                updated_by=owner.id,
            )
        )
        db.commit()

    with session_factory() as db:
        result = rotate_project_key(
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert result.previous_version is None
    assert result.active_version == 1
    assert result.secrets_reencrypted == 1

    with session_factory() as db:
        stored_secret = db.scalar(
            select(Secret).where(Secret.environment_id == environment.id)
        )
        revealed = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="LEGACY_KEY",
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert stored_secret is not None
    assert stored_secret.encryption_key_version == 1
    assert revealed.value == "legacy-value"


def test_failed_rotation_rolls_back_new_key_and_partial_reencryption(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-failed-rotation@example.com")
    project = seeder.project(owner, name="failed-rotation-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        for key, value in (("GOOD_KEY", "good-value"), ("BROKEN_KEY", "broken-value")):
            create_secret(
                project_id=project.id,
                environment_id=environment.id,
                payload=SecretCreateRequest(key=key, value=value),
                project_access=access,
                current_user=owner,
                db=db,
            )

    with session_factory() as db:
        good_secret = db.scalar(
            select(Secret).where(
                Secret.environment_id == environment.id,
                Secret.key == "GOOD_KEY",
            )
        )
        broken_secret = db.scalar(
            select(Secret).where(
                Secret.environment_id == environment.id,
                Secret.key == "BROKEN_KEY",
            )
        )
        assert good_secret is not None
        assert broken_secret is not None
        original_good_ciphertext = good_secret.encrypted_value
        broken_secret.encrypted_value = b"not-valid-ciphertext"
        db.commit()

    with session_factory() as db:
        with pytest.raises(RuntimeError):
            rotate_project_key(
                project_access=access,
                current_user=owner,
                db=db,
            )
        db.rollback()

    with session_factory() as db:
        keys = db.scalars(
            select(ProjectEncryptionKey).where(ProjectEncryptionKey.project_id == project.id)
        ).all()
        good_secret = db.scalar(
            select(Secret).where(
                Secret.environment_id == environment.id,
                Secret.key == "GOOD_KEY",
            )
        )

    assert [(key.version, key.is_active) for key in keys] == [(1, True)]
    assert good_secret is not None
    assert good_secret.encryption_key_version == 1
    assert good_secret.encrypted_value == original_good_ciphertext
