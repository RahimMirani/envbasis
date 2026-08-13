from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.environment import Environment
from app.models.project import Project
from app.models.project_encryption_key import ProjectEncryptionKey
from app.models.secret import Secret
from app.services.crypto import (
    decrypt_secret_value,
    decrypt_with_data_key,
    encrypt_with_data_key,
)
from app.services.root_key_provider import (
    get_active_root_key_provider,
    get_root_key_provider_for_wrapped_key,
)


@dataclass(frozen=True)
class ProjectKeyRotationResult:
    project_id: uuid.UUID
    previous_version: int | None
    active_version: int
    secrets_reencrypted: int
    rotated_at: datetime


def _get_project_or_raise(db: Session, *, project_id: uuid.UUID, lock: bool = False) -> Project:
    statement = select(Project).where(Project.id == project_id)
    if lock:
        statement = statement.with_for_update()
    project = db.scalar(statement)
    if project is None:
        raise ValueError("Project not found.")
    return project


def get_or_create_active_project_key(
    db: Session,
    *,
    project_id: uuid.UUID,
) -> ProjectEncryptionKey:
    _get_project_or_raise(db, project_id=project_id, lock=True)
    active_key = db.scalar(
        select(ProjectEncryptionKey).where(
            ProjectEncryptionKey.project_id == project_id,
            ProjectEncryptionKey.is_active.is_(True),
        )
    )
    if active_key is not None:
        return active_key

    latest_version = db.scalar(
        select(func.max(ProjectEncryptionKey.version)).where(
            ProjectEncryptionKey.project_id == project_id
        )
    )
    generated_key = get_active_root_key_provider().generate_project_data_key(
        project_id=project_id
    )
    key = ProjectEncryptionKey(
        project_id=project_id,
        version=(latest_version or 0) + 1,
        wrapped_key=generated_key.wrapped_key,
        wrapping_provider=generated_key.provider,
        wrapping_key_id=generated_key.key_id,
        is_active=True,
    )
    db.add(key)
    db.flush()
    return key


def encrypt_project_secret(
    db: Session,
    *,
    project_id: uuid.UUID,
    value: str,
) -> tuple[bytes, int]:
    project_key = get_or_create_active_project_key(db, project_id=project_id)
    data_key = get_root_key_provider_for_wrapped_key(
        provider=project_key.wrapping_provider,
        key_id=project_key.wrapping_key_id,
    ).unwrap_project_data_key(
        project_id=project_id,
        wrapped_key=project_key.wrapped_key,
        key_id=project_key.wrapping_key_id,
    )
    return encrypt_with_data_key(value, data_key), project_key.version


def decrypt_project_secret(
    db: Session,
    *,
    project_id: uuid.UUID,
    encrypted_value: bytes,
    encryption_key_version: int | None,
) -> str:
    if encryption_key_version is None:
        return decrypt_secret_value(encrypted_value)

    project_key = db.scalar(
        select(ProjectEncryptionKey).where(
            ProjectEncryptionKey.project_id == project_id,
            ProjectEncryptionKey.version == encryption_key_version,
        )
    )
    if project_key is None:
        raise RuntimeError(
            f"Project encryption key version {encryption_key_version} is not available."
        )
    data_key = get_root_key_provider_for_wrapped_key(
        provider=project_key.wrapping_provider,
        key_id=project_key.wrapping_key_id,
    ).unwrap_project_data_key(
        project_id=project_id,
        wrapped_key=project_key.wrapped_key,
        key_id=project_key.wrapping_key_id,
    )
    return decrypt_with_data_key(encrypted_value, data_key)


def rotate_project_encryption_key(
    db: Session,
    *,
    project_id: uuid.UUID,
) -> ProjectKeyRotationResult:
    _get_project_or_raise(db, project_id=project_id, lock=True)
    previous_key = db.scalar(
        select(ProjectEncryptionKey).where(
            ProjectEncryptionKey.project_id == project_id,
            ProjectEncryptionKey.is_active.is_(True),
        )
    )
    latest_version = db.scalar(
        select(func.max(ProjectEncryptionKey.version)).where(
            ProjectEncryptionKey.project_id == project_id
        )
    )
    next_version = (latest_version or 0) + 1
    generated_key = get_active_root_key_provider().generate_project_data_key(
        project_id=project_id
    )
    new_data_key = generated_key.plaintext_key
    new_key = ProjectEncryptionKey(
        project_id=project_id,
        version=next_version,
        wrapped_key=generated_key.wrapped_key,
        wrapping_provider=generated_key.provider,
        wrapping_key_id=generated_key.key_id,
        is_active=False,
    )
    db.add(new_key)
    db.flush()

    secret_rows = list(
        db.scalars(
            select(Secret)
            .join(Environment, Environment.id == Secret.environment_id)
            .where(Environment.project_id == project_id)
            .order_by(Secret.id.asc())
        ).all()
    )
    for secret in secret_rows:
        plaintext = decrypt_project_secret(
            db,
            project_id=project_id,
            encrypted_value=secret.encrypted_value,
            encryption_key_version=secret.encryption_key_version,
        )
        secret.encrypted_value = encrypt_with_data_key(plaintext, new_data_key)
        secret.encryption_key_version = next_version

    rotated_at = datetime.now(timezone.utc)
    if previous_key is not None:
        previous_key.is_active = False
        previous_key.retired_at = rotated_at
        db.flush([previous_key])
    new_key.is_active = True
    db.flush()

    return ProjectKeyRotationResult(
        project_id=project_id,
        previous_version=previous_key.version if previous_key is not None else None,
        active_version=next_version,
        secrets_reencrypted=len(secret_rows),
        rotated_at=rotated_at,
    )
