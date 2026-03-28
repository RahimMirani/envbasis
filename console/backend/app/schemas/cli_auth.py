from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field

CliAuthState = Literal["pending", "approved", "denied", "expired", "consumed"]


class CliAuthStartRequest(BaseModel):
    client_name: str | None = Field(default=None, max_length=255)
    device_name: str | None = Field(default=None, max_length=255)
    cli_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=64)


class CliAuthStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_url: str
    verification_url_complete: str
    expires_in: int
    interval: int


class CliAuthCodeRequest(BaseModel):
    user_code: str = Field(min_length=3, max_length=32)


class CliAuthResolveResponse(BaseModel):
    status: CliAuthState
    user_code: str
    client_name: str | None
    device_name: str | None
    cli_version: str | None
    platform: str | None
    expires_at: datetime
    requested_at: datetime


class CliAuthTokenRequest(BaseModel):
    device_code: str = Field(min_length=16, max_length=512)


class CliAuthTokenPollResponse(BaseModel):
    error: Literal["authorization_pending", "slow_down"]
    interval: int


class CliAuthTokenErrorResponse(BaseModel):
    error: Literal["expired_token", "access_denied", "already_used", "invalid_device_code", "invalid_refresh_token"]


class CliAuthUserRead(BaseModel):
    id: uuid.UUID
    email: str


class CliAuthTokenSuccessResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    user: CliAuthUserRead


class CliAuthRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=1024)


class CliAuthLogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=1024)


class CliAuthLogoutResponse(BaseModel):
    revoked: bool
