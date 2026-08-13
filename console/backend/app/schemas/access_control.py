from __future__ import annotations

from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field, model_validator


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    created_at: datetime


class RolePermissionInput(BaseModel):
    resource: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    effect: Literal["allow", "deny"] = "allow"
    environment_id: uuid.UUID | None = None
    path: str | None = Field(default=None, max_length=1000)
    recursive: bool = True


class RolePermissionRead(RolePermissionInput):
    id: uuid.UUID


class AccessRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[RolePermissionInput] = Field(min_length=1)
    organization_id: uuid.UUID | None = None


class AccessRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[RolePermissionInput] | None = None


class AccessRoleRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    is_builtin: bool
    permissions: list[RolePermissionRead]
    created_at: datetime


class RoleAssignmentCreate(BaseModel):
    role_id: uuid.UUID
    user_id: uuid.UUID | None = None
    machine_identity_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one_subject(self) -> "RoleAssignmentCreate":
        if (self.user_id is None) == (self.machine_identity_id is None):
            raise ValueError("Provide exactly one user_id or machine_identity_id.")
        return self


class RoleAssignmentRead(RoleAssignmentCreate):
    id: uuid.UUID
    created_at: datetime


class PermissionSimulationRequest(BaseModel):
    user_id: uuid.UUID | None = None
    machine_identity_id: uuid.UUID | None = None
    resource: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    environment_id: uuid.UUID | None = None
    path: str | None = None

    @model_validator(mode="after")
    def exactly_one_subject(self) -> "PermissionSimulationRequest":
        if (self.user_id is None) == (self.machine_identity_id is None):
            raise ValueError("Provide exactly one user_id or machine_identity_id.")
        return self


class PermissionSimulationRead(BaseModel):
    allowed: bool
    assigned: bool
    reason: str
    matched_role_ids: list[uuid.UUID]
    matched_permission_ids: list[uuid.UUID]
