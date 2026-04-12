from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, EmailStr, Field, model_validator


class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: Literal["member"] = "member"
    can_push_pull_secrets: bool = False
    can_manage_runtime_tokens: bool = False
    can_manage_team: bool = False
    can_view_audit_logs: bool = False


class MemberRevokeRequest(BaseModel):
    email: EmailStr
    shared_token_action: Literal["keep_active", "revoke_tokens"] | None = None


class MemberBulkRevokeRequest(BaseModel):
    emails: list[EmailStr] = Field(min_length=1)
    shared_token_action: Literal["keep_active", "revoke_tokens"] | None = None


class MemberPermissionUpdateRequest(BaseModel):
    email: EmailStr
    can_push_pull_secrets: bool | None = None
    can_manage_runtime_tokens: bool | None = None
    can_manage_team: bool | None = None
    can_view_audit_logs: bool | None = None

    @model_validator(mode="after")
    def validate_has_changes(self) -> "MemberPermissionUpdateRequest":
        if (
            self.can_push_pull_secrets is None
            and self.can_manage_runtime_tokens is None
            and self.can_manage_team is None
            and self.can_view_audit_logs is None
        ):
            raise ValueError("At least one permission must be provided.")
        return self


class MemberBulkPermissionUpdateRequest(BaseModel):
    emails: list[EmailStr] = Field(min_length=1)
    can_push_pull_secrets: bool | None = None
    can_manage_runtime_tokens: bool | None = None
    can_manage_team: bool | None = None
    can_view_audit_logs: bool | None = None

    @model_validator(mode="after")
    def validate_has_changes(self) -> "MemberBulkPermissionUpdateRequest":
        if (
            self.can_push_pull_secrets is None
            and self.can_manage_runtime_tokens is None
            and self.can_manage_team is None
            and self.can_view_audit_logs is None
        ):
            raise ValueError("At least one permission must be provided.")
        return self


class ProjectMemberRead(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    role: str
    can_push_pull_secrets: bool
    can_manage_runtime_tokens: bool = False
    can_manage_team: bool = False
    can_view_audit_logs: bool = False
    joined_at: datetime
