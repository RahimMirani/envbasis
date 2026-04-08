from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.services.secrets import validate_secret_mapping


class SecretPushRequest(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)

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
    version: int
    updated_at: datetime
    updated_by_user_id: uuid.UUID | None = None
    updated_by_email: str | None = None


class SecretRevealResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    value: str
    version: int
    updated_at: datetime
    updated_by_user_id: uuid.UUID | None = None
    updated_by_email: str | None = None
    revealed_at: datetime


class SecretListResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: list[SecretItemRead]
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


class SecretUpdateRequest(BaseModel):
    value: str


class SecretMutationResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    version: int
    updated_at: datetime
    changed: bool


class SecretDeleteResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    version: int
    deleted_at: datetime


class SecretPushResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    total_received: int
    changed: int
    unchanged: int
    versions: list[SecretVersionRead]


class SecretPullResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: dict[str, str]
    versions: dict[str, int]
    generated_at: datetime
