from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, EmailStr


class RuntimeTokenShareRequest(BaseModel):
    email: EmailStr
    can_manage: bool = False


class RuntimeTokenShareRead(BaseModel):
    id: uuid.UUID
    runtime_token_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    shared_by: uuid.UUID | None
    can_manage: bool
    created_at: datetime


class RuntimeTokenRevealResponse(BaseModel):
    token_id: uuid.UUID
    plaintext_token: str
