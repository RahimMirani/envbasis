from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, EmailStr, Field


class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: Literal["member"] = "member"
    can_push_pull_secrets: bool = True


class MemberRevokeRequest(BaseModel):
    email: EmailStr
    shared_token_action: Literal["keep_active", "revoke_tokens"] | None = None


class MemberBulkRevokeRequest(BaseModel):
    emails: list[EmailStr] = Field(min_length=1)
    shared_token_action: Literal["keep_active", "revoke_tokens"] | None = None


class MemberAccessUpdateRequest(BaseModel):
    email: EmailStr
    can_push_pull_secrets: bool


class ProjectMemberRead(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    role: str
    can_push_pull_secrets: bool
    joined_at: datetime
