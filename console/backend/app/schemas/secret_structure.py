from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, field_validator

from app.services.secret_structure import normalize_secret_path, normalize_secret_tags


class SecretFolderCreate(BaseModel):
    path: str = Field(max_length=512)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return normalize_secret_path(value)


class SecretFolderRead(BaseModel):
    id: uuid.UUID | None = None
    environment_id: uuid.UUID
    path: str
    parent_path: str
    name: str
    description: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None
    synthetic: bool = False


class SecretFolderListResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    path: str
    recursive: bool
    folders: list[SecretFolderRead]


class ProjectSecretTagCreate(BaseModel):
    name: str
    color: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_secret_tags([value])[0]


class ProjectSecretTagUpdate(BaseModel):
    color: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=500)


class ProjectSecretTagRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    color: str | None = None
    description: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
