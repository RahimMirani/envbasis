from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field, model_validator


class ApprovalStep(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    min_approvals: int = Field(default=1, ge=1, le=20)
    approver_user_ids: list[uuid.UUID] = Field(default_factory=list)
    approver_role_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def approvers_required(self) -> "ApprovalStep":
        if not self.approver_user_ids and not self.approver_role_ids:
            raise ValueError("Each approval step needs at least one user or role approver.")
        return self


class ApprovalPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    environment_id: uuid.UUID | None = None
    path: str = "/"
    recursive: bool = True
    actions: list[Literal["create", "update", "delete"]] = Field(min_length=1)
    steps: list[ApprovalStep] = Field(min_length=1)
    prevent_self_approval: bool = True
    enabled: bool = True


class ApprovalPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    environment_id: uuid.UUID | None = None
    path: str | None = None
    recursive: bool | None = None
    actions: list[Literal["create", "update", "delete"]] | None = None
    steps: list[ApprovalStep] | None = None
    prevent_self_approval: bool | None = None
    enabled: bool | None = None


class ApprovalPolicyRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    environment_id: uuid.UUID | None
    path: str
    recursive: bool
    actions: list[str]
    steps: list[ApprovalStep]
    prevent_self_approval: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SecretChangeProposal(BaseModel):
    environment_id: uuid.UUID
    path: str = "/"
    secret_key: str = Field(min_length=1, max_length=128)
    operation: Literal["create", "update", "delete"]
    value: str | None = None
    metadata: dict = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def value_required(self) -> "SecretChangeProposal":
        if self.operation in {"create", "update"} and self.value is None:
            raise ValueError("A value is required for create and update proposals.")
        return self


class ApprovalEventRead(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    step: int | None
    comment: str | None
    created_at: datetime


class ApprovalRequestRead(BaseModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    path: str
    secret_key: str
    operation: str
    metadata: dict
    status: str
    current_step: int
    total_steps: int
    author_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None
    events: list[ApprovalEventRead] = Field(default_factory=list)


class ApprovalAction(BaseModel):
    action: Literal["approve", "reject", "cancel", "comment"]
    comment: str | None = Field(default=None, max_length=2000)
