from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.services.secrets import validate_secret_mapping


class SecretPushRequest(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)
    path: str = "/"
    tags: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=320)
    service: str | None = Field(default=None, max_length=128)
    rotation_interval_days: int | None = Field(default=None, ge=1, le=3650)
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("secrets")
    @classmethod
    def validate_secrets(cls, value: dict[str, str]) -> dict[str, str]:
        validate_secret_mapping(value)
        return value


class SecretVersionRead(BaseModel):
    key: str
    version: int
    updated_at: datetime


class SecretItemRead(BaseModel):
    key: str
    path: str = "/"
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    owner: str | None = None
    service: str | None = None
    rotation_interval_days: int | None = None
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)
    is_reference: bool = False
    version: int
    updated_at: datetime
    expires_at: datetime | None = None
    updated_by_user_id: uuid.UUID | None = None
    updated_by_email: str | None = None


class SecretRevealResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    value: str
    path: str = "/"
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    owner: str | None = None
    service: str | None = None
    rotation_interval_days: int | None = None
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)
    is_reference: bool = False
    version: int
    updated_at: datetime
    expires_at: datetime | None = None
    updated_by_user_id: uuid.UUID | None = None
    updated_by_email: str | None = None
    revealed_at: datetime


class SecretListResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: list[SecretItemRead]
    generated_at: datetime


class ProjectSecretItemRead(SecretItemRead):
    environment_id: uuid.UUID
    environment_name: str


class ProjectSecretListResponse(BaseModel):
    project_id: uuid.UUID
    secrets: list[ProjectSecretItemRead]
    next_cursor: str | None = None
    generated_at: datetime


class EnvironmentSecretStatsRead(BaseModel):
    environment_id: uuid.UUID
    environment_name: str
    secret_count: int
    last_updated_at: datetime | None = None
    last_activity_at: datetime | None = None


class ProjectSecretStatsResponse(BaseModel):
    project_id: uuid.UUID
    total_secret_count: int
    environments: list[EnvironmentSecretStatsRead]
    generated_at: datetime


class SecretCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str
    expires_at: datetime | None = None
    path: str = "/"
    tags: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=320)
    service: str | None = Field(default=None, max_length=128)
    rotation_interval_days: int | None = Field(default=None, ge=1, le=3650)
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)


class SecretUpdateRequest(BaseModel):
    value: str
    expires_at: datetime | None = None
    path: str | None = None
    tags: list[str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=320)
    service: str | None = Field(default=None, max_length=128)
    rotation_interval_days: int | None = Field(default=None, ge=1, le=3650)
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] | None = None


class SecretMutationResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    path: str = "/"
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    owner: str | None = None
    service: str | None = None
    rotation_interval_days: int | None = None
    rotate_at: datetime | None = None
    custom_metadata: dict[str, str] = Field(default_factory=dict)
    is_reference: bool = False
    version: int
    updated_at: datetime
    expires_at: datetime | None = None
    changed: bool


class SecretDeleteResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    path: str = "/"
    version: int
    deleted_at: datetime


class SecretPushResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    total_received: int
    changed: int
    unchanged: int
    versions: list[SecretVersionRead]


class ResolvedSecretItem(BaseModel):
    key: str
    value: str
    version: int
    source: str
    source_environment_id: uuid.UUID
    source_path: str
    value_kind: str
    referenced_keys: list[str] = Field(default_factory=list)
    resolved: bool
    error: str | None = None


class SecretPullResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: dict[str, str]
    versions: dict[str, int]
    items: list[ResolvedSecretItem] = Field(default_factory=list)
    resolution_mode: str = "resolved"
    includes_imports: bool = True
    resolution_errors: list[str] = Field(default_factory=list)
    generated_at: datetime


class SecretBulkDeleteItem(BaseModel):
    environment_id: uuid.UUID
    key: str = Field(min_length=1, max_length=128)
    path: str = "/"


class SecretBulkDeleteRequest(BaseModel):
    items: list[SecretBulkDeleteItem] = Field(min_length=1)
