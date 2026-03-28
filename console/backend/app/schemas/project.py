from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_has_changes(self) -> "ProjectUpdate":
        if self.name is None and self.description is None:
            raise ValueError("At least one project field must be provided.")
        return self


class ProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    owner_id: uuid.UUID
    role: str
    created_at: datetime
    environment_count: int = 0
    member_count: int = 0
    runtime_token_count: int = 0
    last_activity_at: datetime | None = None
