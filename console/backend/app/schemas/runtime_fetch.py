from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel


class RuntimeSecretsResponse(BaseModel):
    project_id: uuid.UUID
    environment_id: uuid.UUID
    secrets: dict[str, str]
    generated_at: datetime

