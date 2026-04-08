from __future__ import annotations

from collections.abc import Mapping, Sequence
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.environment import Environment
from app.models.secret import Secret
from app.services.crypto import decrypt_secret_value

MAX_SECRET_KEYS = 100
MAX_SECRET_KEY_LENGTH = 128
MAX_SECRET_VALUE_BYTES = 16 * 1024
MAX_SECRET_TOTAL_BYTES = 256 * 1024


def validate_secret_mapping(secrets: Mapping[str, str]) -> None:
    if len(secrets) > MAX_SECRET_KEYS:
        raise ValueError(f"Too many secrets. Maximum allowed per push is {MAX_SECRET_KEYS}.")

    total_bytes = 0
    for raw_key, value in secrets.items():
        key = raw_key.strip()
        if not key:
            raise ValueError("Secret keys cannot be empty.")
        if len(key) > MAX_SECRET_KEY_LENGTH:
            raise ValueError(f"Secret key '{key}' is too long. Maximum length is {MAX_SECRET_KEY_LENGTH}.")

        value_bytes = len(value.encode("utf-8"))
        if value_bytes > MAX_SECRET_VALUE_BYTES:
            raise ValueError(
                f"Secret '{key}' is too large. Maximum value size is {MAX_SECRET_VALUE_BYTES} bytes."
            )

        total_bytes += len(key.encode("utf-8")) + value_bytes
        if total_bytes > MAX_SECRET_TOTAL_BYTES:
            raise ValueError(
                f"Total secret payload is too large. Maximum payload size is {MAX_SECRET_TOTAL_BYTES} bytes."
            )


def validate_single_secret(*, key: str, value: str) -> None:
    validate_secret_mapping({key: value})


def build_secret_payload(secret_rows: Sequence[Secret]) -> tuple[dict[str, str], dict[str, int]]:
    if len(secret_rows) > MAX_SECRET_KEYS:
        raise ValueError(f"Stored secret set is too large. Maximum allowed keys is {MAX_SECRET_KEYS}.")

    secrets: dict[str, str] = {}
    versions: dict[str, int] = {}
    total_bytes = 0

    for row in secret_rows:
        value = decrypt_secret_value(row.encrypted_value)
        value_bytes = len(value.encode("utf-8"))
        if value_bytes > MAX_SECRET_VALUE_BYTES:
            raise ValueError(
                f"Stored secret '{row.key}' is too large. Maximum value size is {MAX_SECRET_VALUE_BYTES} bytes."
            )

        total_bytes += len(row.key.encode("utf-8")) + value_bytes
        if total_bytes > MAX_SECRET_TOTAL_BYTES:
            raise ValueError(
                f"Stored secret payload is too large. Maximum payload size is {MAX_SECRET_TOTAL_BYTES} bytes."
            )

        secrets[row.key] = value
        versions[row.key] = row.version

    return secrets, versions


def get_latest_secret_rows(
    db: Session,
    *,
    environment_id: uuid.UUID,
    include_deleted: bool = False,
    key_filter: str | None = None,
) -> list[Secret]:
    latest_versions = (
        select(
            Secret.key.label("key"),
            func.max(Secret.version).label("latest_version"),
        )
        .where(Secret.environment_id == environment_id)
        .group_by(Secret.key)
        .subquery()
    )

    stmt = (
        select(Secret)
        .join(
            latest_versions,
            (Secret.key == latest_versions.c.key)
            & (Secret.version == latest_versions.c.latest_version),
        )
        .where(Secret.environment_id == environment_id)
        .order_by(Secret.key.asc())
    )
    if not include_deleted:
        stmt = stmt.where(Secret.is_deleted.is_(False))
    if key_filter:
        stmt = stmt.where(Secret.key.ilike(f"%{key_filter}%"))

    rows = db.execute(stmt).scalars().all()
    return list(rows)


def get_project_secret_stats(
    db: Session,
    *,
    project_id: uuid.UUID,
) -> list[dict[str, object]]:
    latest_versions = (
        select(
            Secret.environment_id.label("environment_id"),
            Secret.key.label("key"),
            func.max(Secret.version).label("latest_version"),
        )
        .join(Environment, Environment.id == Secret.environment_id)
        .where(Environment.project_id == project_id)
        .group_by(Secret.environment_id, Secret.key)
        .subquery()
    )

    latest_active_secret_stats = (
        select(
            Secret.environment_id.label("environment_id"),
            func.count(Secret.id).label("secret_count"),
            func.max(Secret.updated_at).label("last_updated_at"),
        )
        .join(
            latest_versions,
            (Secret.environment_id == latest_versions.c.environment_id)
            & (Secret.key == latest_versions.c.key)
            & (Secret.version == latest_versions.c.latest_version),
        )
        .where(Secret.is_deleted.is_(False))
        .group_by(Secret.environment_id)
        .subquery()
    )

    latest_secret_activity = (
        select(
            Secret.environment_id.label("environment_id"),
            func.max(Secret.updated_at).label("last_activity_at"),
        )
        .join(
            latest_versions,
            (Secret.environment_id == latest_versions.c.environment_id)
            & (Secret.key == latest_versions.c.key)
            & (Secret.version == latest_versions.c.latest_version),
        )
        .group_by(Secret.environment_id)
        .subquery()
    )

    rows = db.execute(
        select(
            Environment.id,
            Environment.name,
            func.coalesce(latest_active_secret_stats.c.secret_count, 0),
            latest_active_secret_stats.c.last_updated_at,
            latest_secret_activity.c.last_activity_at,
        )
        .outerjoin(
            latest_active_secret_stats,
            latest_active_secret_stats.c.environment_id == Environment.id,
        )
        .outerjoin(
            latest_secret_activity,
            latest_secret_activity.c.environment_id == Environment.id,
        )
        .where(Environment.project_id == project_id)
        .order_by(Environment.created_at.asc())
    ).all()

    return [
        {
            "environment_id": environment_id,
            "environment_name": environment_name,
            "secret_count": int(secret_count),
            "last_updated_at": last_updated_at,
            "last_activity_at": last_activity_at,
        }
        for (
            environment_id,
            environment_name,
            secret_count,
            last_updated_at,
            last_activity_at,
        ) in rows
    ]
