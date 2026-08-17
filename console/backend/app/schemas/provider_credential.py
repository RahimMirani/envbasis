from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field


ProviderName = Literal["openai", "anthropic", "github"]


class ProviderCredentialRead(BaseModel):
    provider: ProviderName
    configured: bool = True
    key_last4: str
    updated_at: datetime
    updated_by: uuid.UUID | None = None


class ProviderCredentialUpsert(BaseModel):
    provider: ProviderName
    secret: str = Field(min_length=1, max_length=4096)


class ProviderCredentialListResponse(BaseModel):
    items: list[ProviderCredentialRead]


class ProxyCredentialResolveRequest(BaseModel):
    machine_access_token: str = Field(min_length=1)
    provider: ProviderName


class ProxyCredentialResolveResponse(BaseModel):
    provider: ProviderName
    secret: str
