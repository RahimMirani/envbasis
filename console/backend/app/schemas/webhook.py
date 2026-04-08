from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


SUPPORTED_EVENTS = {
    "secret.created",
    "secret.updated",
    "secret.deleted",
    "secrets.pushed",
    "member.joined",
    "member.revoked",
    "runtime_token.created",
    "runtime_token.revoked",
    "*",
}


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)

    def validate_events(self) -> None:
        invalid = [e for e in self.events if e not in SUPPORTED_EVENTS]
        if invalid:
            raise ValueError(f"Unsupported events: {invalid}. Supported: {sorted(SUPPORTED_EVENTS)}")


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    events: list[str]
    signing_secret: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
