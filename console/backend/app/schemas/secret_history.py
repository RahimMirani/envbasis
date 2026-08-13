from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.services.secret_structure import normalize_secret_path


class SecretVersionItem(BaseModel):
    key: str
    path: str
    version: int
    is_deleted: bool
    is_reference: bool
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    owner: str | None = None
    service: str | None = None
    rotation_interval_days: int | None = None
    rotate_at: datetime | None = None
    expires_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)
    updated_by_user_id: uuid.UUID | None = None
    updated_by_email: str | None = None
    updated_at: datetime
    archived_at: datetime | None = None


class SecretVersionListResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    path: str
    versions: list[SecretVersionItem]


class SecretHistoricalRevealResponse(SecretVersionItem):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    value: str
    revealed_at: datetime


class SecretRollbackResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    path: str
    source_version: int
    version: int
    updated_at: datetime


class RecoveryRequest(BaseModel):
    at: datetime
    path: str = "/"
    recursive: bool = False
    dry_run: bool = False

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return normalize_secret_path(value)


class RecoveryItem(BaseModel):
    key: str
    path: str
    snapshot_version: int | None = None
    current_version: int | None = None
    action: str


class RecoveryResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID | None = None
    at: datetime
    dry_run: bool
    changed: int
    environments_changed: int = 0
    items: list[RecoveryItem] = Field(default_factory=list)


class SecretRetentionUpdate(BaseModel):
    retain_versions: int = Field(ge=1, le=1000)
    retain_days: int | None = Field(default=None, ge=1, le=3650)
    archive_deleted_after_days: int | None = Field(default=None, ge=0, le=3650)


class SecretRetentionRead(SecretRetentionUpdate):
    project_id: uuid.UUID
