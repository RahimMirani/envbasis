from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal
import uuid

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None
    environment_name: str | None
    user_id: uuid.UUID | None
    actor_email: str | None
    action: str
    metadata_json: dict[str, Any] | None
    created_at: datetime


class UnifiedAuditLogRead(BaseModel):
    id: uuid.UUID
    source: Literal["project", "cli_auth"]
    project_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    environment_name: str | None
    cli_auth_session_id: uuid.UUID | None
    user_id: uuid.UUID | None
    actor_email: str | None
    action: str
    metadata_json: dict[str, Any] | None
    created_at: datetime
