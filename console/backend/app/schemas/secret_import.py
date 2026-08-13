from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.services.secret_structure import normalize_secret_path


class SecretImportCreate(BaseModel):
    target_environment_id: uuid.UUID
    target_path: str = "/"
    source_environment_id: uuid.UUID
    source_path: str = "/"
    recursive: bool = False
    priority: int = Field(default=0, ge=-1000, le=1000)
    enabled: bool = True

    @field_validator("target_path", "source_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return normalize_secret_path(value)


class SecretImportUpdate(BaseModel):
    recursive: bool | None = None
    priority: int | None = Field(default=None, ge=-1000, le=1000)
    enabled: bool | None = None


class SecretImportRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    target_environment_id: uuid.UUID
    target_path: str
    source_environment_id: uuid.UUID
    source_path: str
    recursive: bool
    priority: int
    enabled: bool
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
