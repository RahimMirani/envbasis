from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ProjectInvitationRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    email: EmailStr
    role: str
    can_push_pull_secrets: bool
    invited_by_email: str | None = None
    status: str
    expires_at: datetime
    last_sent_at: datetime | None = None
    send_count: int
    cooldown_until: datetime | None = None
    created_at: datetime


class InvitationSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    inviter_email: str | None = None
    email: EmailStr
    role: str
    can_push_pull_secrets: bool
    status: Literal["pending"] = "pending"
    expires_at: datetime
    created_at: datetime


class InvitationDetail(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    inviter_email: str | None = None
    email: EmailStr
    role: str
    can_push_pull_secrets: bool
    status: str
    expires_at: datetime
    created_at: datetime


class InviteMemberResponse(BaseModel):
    """Response for POST /projects/{id}/invite — pending invitation created or resent."""

    invitation: ProjectInvitationRead
    email_sent: bool = True
    message: str | None = None
