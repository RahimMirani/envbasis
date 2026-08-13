from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field, model_validator


MachineAction = Literal["secrets:read"]


class MachineIdentityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    environment_id: uuid.UUID | None = None
    scope: Literal["project", "organization"] = "project"
    allowed_actions: list[MachineAction] = Field(default_factory=lambda: ["secrets:read"], min_length=1)
    allowed_secret_keys: list[str] | None = None
    trusted_cidrs: list[str] = Field(default_factory=list)
    access_token_ttl_seconds: int | None = None
    credential_expires_at: datetime | None = None

    @model_validator(mode="after")
    def environment_for_project(self) -> "MachineIdentityCreate":
        if self.scope == "project" and self.environment_id is None:
            raise ValueError("Project-scoped identities require an environment.")
        return self


class MachineIdentityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    environment_id: uuid.UUID | None = None
    allowed_actions: list[MachineAction] | None = Field(default=None, min_length=1)
    allowed_secret_keys: list[str] | None = None
    trusted_cidrs: list[str] | None = None
    access_token_ttl_seconds: int | None = None
    credential_expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_has_changes(self) -> "MachineIdentityUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one machine identity field must be provided.")
        return self


class MachineIdentityRotateSecretRequest(BaseModel):
    credential_expires_at: datetime | None = None
    credential_id: uuid.UUID | None = None
    overlap_seconds: int | None = Field(default=None, ge=0, le=604800)


class MachineCredentialCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=255)
    credential_expires_at: datetime | None = None


class MachineCredentialRead(BaseModel):
    id: uuid.UUID
    identity_id: uuid.UUID
    name: str
    auth_method: str
    client_id: str
    version: int
    expires_at: datetime | None
    overlap_expires_at: datetime | None
    revoked_at: datetime | None
    last_authenticated_at: datetime | None
    created_at: datetime


class MachineCredentialResponse(MachineCredentialRead):
    client_secret: str


class MachineAuthEventRead(BaseModel):
    id: uuid.UUID
    credential_id: uuid.UUID | None
    client_id: str
    client_ip: str | None
    success: bool
    reason: str
    created_at: datetime


class MachineIdentityRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None
    name: str
    client_id: str
    credential_version: int
    credential_expires_at: datetime | None
    access_token_ttl_seconds: int
    allowed_actions: list[str]
    allowed_secret_keys: list[str] | None
    trusted_cidrs: list[str]
    created_by: uuid.UUID | None
    revoked_at: datetime | None
    disabled_at: datetime | None = None
    locked_until: datetime | None = None
    failed_auth_attempts: int = 0
    credentials: list[MachineCredentialRead] = Field(default_factory=list)
    last_authenticated_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MachineIdentityCredentialResponse(MachineIdentityRead):
    client_secret: str


class MachineTokenRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=1024)


class MachineTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    expires_at: datetime


class MachineSecretsResponse(BaseModel):
    machine_identity_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: dict[str, str]
    generated_at: datetime
