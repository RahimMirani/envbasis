from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_secret_tag import ProjectSecretTag
from app.models.secret_folder import SecretFolder

MAX_SECRET_PATH_LENGTH = 512
MAX_SECRET_TAGS = 20
MAX_SECRET_TAG_LENGTH = 32
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


def normalize_secret_path(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return "/"
    if not candidate.startswith("/"):
        candidate = f"/{candidate}"

    raw_segments = candidate.split("/")
    if any(segment in {".", ".."} for segment in raw_segments):
        raise ValueError("Secret path cannot contain . or .. segments.")

    segments = [segment for segment in raw_segments if segment]
    if any(len(segment) > 128 for segment in segments):
        raise ValueError("Secret path segments cannot exceed 128 characters.")
    if any("\\" in segment or "\x00" in segment for segment in segments):
        raise ValueError("Secret path contains an invalid character.")

    normalized = "/" + "/".join(segments) if segments else "/"
    if len(normalized) > MAX_SECRET_PATH_LENGTH:
        raise ValueError(
            f"Secret path is too long. Maximum length is {MAX_SECRET_PATH_LENGTH} characters."
        )
    return normalized


def secret_parent_path(path: str) -> str:
    normalized = normalize_secret_path(path)
    if normalized == "/":
        return "/"
    parent = normalized.rsplit("/", 1)[0]
    return parent or "/"


def path_is_within(candidate: str, parent: str, *, include_parent: bool = True) -> bool:
    normalized_candidate = normalize_secret_path(candidate)
    normalized_parent = normalize_secret_path(parent)
    if normalized_candidate == normalized_parent:
        return include_parent
    if normalized_parent == "/":
        return normalized_candidate.startswith("/")
    return normalized_candidate.startswith(f"{normalized_parent}/")


def normalize_secret_tags(values: list[str]) -> list[str]:
    if len(values) > MAX_SECRET_TAGS:
        raise ValueError(f"Too many secret tags. Maximum is {MAX_SECRET_TAGS}.")

    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip().lower()
        if not _TAG_PATTERN.fullmatch(value):
            raise ValueError(
                "Tags must be 1-32 characters, start with a letter or number, and use only letters, numbers, dash, underscore, or dot."
            )
        if value not in normalized:
            normalized.append(value)
    return normalized


def ensure_secret_folder(
    db: Session,
    *,
    environment_id: uuid.UUID,
    path: str,
    created_by: uuid.UUID | None,
    description: str | None = None,
) -> list[SecretFolder]:
    normalized = normalize_secret_path(path)
    if normalized == "/":
        return []

    existing_paths = set(
        db.scalars(
            select(SecretFolder.path).where(SecretFolder.environment_id == environment_id)
        ).all()
    )
    created: list[SecretFolder] = []
    current = ""
    segments = normalized.lstrip("/").split("/")
    for index, segment in enumerate(segments):
        parent = current or "/"
        current = f"{current}/{segment}" if current else f"/{segment}"
        if current in existing_paths:
            continue
        folder = SecretFolder(
            environment_id=environment_id,
            path=current,
            parent_path=parent,
            name=segment,
            description=description if index == len(segments) - 1 else None,
            created_by=created_by,
        )
        db.add(folder)
        db.flush()
        created.append(folder)
        existing_paths.add(current)
    return created


def ensure_project_tags(
    db: Session,
    *,
    project_id: uuid.UUID,
    tags: list[str],
    created_by: uuid.UUID | None,
) -> None:
    normalized = normalize_secret_tags(tags)
    if not normalized:
        return
    existing = set(
        db.scalars(
            select(ProjectSecretTag.name).where(
                ProjectSecretTag.project_id == project_id,
                ProjectSecretTag.name.in_(normalized),
            )
        ).all()
    )
    for name in normalized:
        if name not in existing:
            db.add(
                ProjectSecretTag(
                    project_id=project_id,
                    name=name,
                    created_by=created_by,
                )
            )
