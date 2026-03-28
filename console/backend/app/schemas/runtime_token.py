from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class RuntimeTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None


class RuntimeTokenNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class RuntimeTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    name: str
    expires_at: datetime | None
    created_by: uuid.UUID | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class RuntimeTokenCreateResponse(RuntimeTokenRead):
    plaintext_token: str
