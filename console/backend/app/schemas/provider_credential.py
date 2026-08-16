from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field


ProviderName = Literal["openai", "anthropic", "github"]


class ProviderCredentialUpsert(BaseModel):
    provider: ProviderName
    secret: str = Field(min_length=1, max_length=4096)


class ProviderCredentialRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    provider: ProviderName
    key_last4: str
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProviderCredentialListResponse(BaseModel):
    credentials: list[ProviderCredentialRead]


class ProxyCredentialResolveRequest(BaseModel):
    machine_access_token: str = Field(min_length=1, max_length=8192)
    provider: ProviderName


class ProxyCredentialResolveResponse(BaseModel):
    provider: ProviderName
    credential: str
    project_id: uuid.UUID
    environment_id: uuid.UUID
    machine_identity_id: uuid.UUID
    credential_version: int
