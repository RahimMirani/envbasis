from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Endpoint(StrEnum):
    AUTH_ME = "/auth/me"
    CLI_AUTH_START = "/cli/auth/start"
    CLI_AUTH_TOKEN = "/cli/auth/token"
    CLI_AUTH_REFRESH = "/cli/auth/refresh"
    CLI_AUTH_LOGOUT = "/cli/auth/logout"
    PROJECTS = "/projects"
    PROJECT_DETAIL = "/projects/{project_id}"
    ENVIRONMENTS = "/projects/{project_id}/environments"
    SECRETS_PUSH = "/projects/{project_id}/environments/{environment_id}/secrets/push"
    SECRETS_PULL = "/projects/{project_id}/environments/{environment_id}/secrets/pull"
    SECRETS_LIST = "/projects/{project_id}/environments/{environment_id}/secrets"
    SECRET_REVEAL = "/projects/{project_id}/environments/{environment_id}/secrets/{key}/reveal"
    SECRETS_STATS = "/projects/{project_id}/secrets/stats"
    SECRET_DETAIL = "/projects/{project_id}/environments/{environment_id}/secrets/{key}"
    MEMBERS = "/projects/{project_id}/members"
    INVITE = "/projects/{project_id}/invite"
    MEMBER_ACCESS = "/projects/{project_id}/members/access"
    REVOKE_MEMBER = "/projects/{project_id}/revoke"
    RUNTIME_TOKENS = "/projects/{project_id}/runtime-tokens"
    CREATE_RUNTIME_TOKEN = "/projects/{project_id}/environments/{environment_id}/runtime-tokens"
    REVEAL_RUNTIME_TOKEN_BY_NAME = "/projects/{project_id}/runtime-tokens/reveal-by-name"
    REVOKE_RUNTIME_TOKEN_BY_NAME = "/projects/{project_id}/runtime-tokens/revoke-by-name"
    TOKEN_SHARE = "/runtime-tokens/{token_id}/share"
    TOKEN_SHARES = "/runtime-tokens/{token_id}/shares"
    AUDIT_LOGS = "/projects/{project_id}/audit-logs"


def build_path(endpoint: Endpoint, **params: str) -> str:
    return endpoint.value.format(**params)


class ErrorPayload(BaseModel):
    detail: str | dict[str, Any] | list[Any] | None = None
    code: str | None = None


class UserProfile(BaseModel):
    id: str
    email: str


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    role: str | None = None
    environment_count: int | None = None
    member_count: int | None = None
    token_count: int | None = None
    last_activity_at: str | None = None


class ProjectDetail(ProjectSummary):
    created_at: str | None = None
    updated_at: str | None = None


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class EnvironmentSummary(BaseModel):
    id: str
    name: str
    created_at: str | None = None
    updated_at: str | None = None


class CreateEnvironmentRequest(BaseModel):
    name: str


class SecretMetadata(BaseModel):
    key: str
    version: int | None = None
    updated_at: str | None = None
    updated_by: str | None = None
    value: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if "updated_by" not in normalized and "updated_by_email" in normalized:
            normalized["updated_by"] = normalized["updated_by_email"]
        return normalized


class RevealedSecret(BaseModel):
    key: str
    value: str
    version: int | None = None
    updated_at: str | None = None
    updated_by_email: str | None = None
    revealed_at: str | None = None


class SecretsListResponse(BaseModel):
    project_id: str | None = None
    environment_id: str | None = None
    environment_name: str | None = None
    retrieved_at: str | None = None
    secrets: list[SecretMetadata] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {"secrets": value}

        if isinstance(value, dict):
            for key in ("secrets", "items", "data"):
                nested = value.get(key)
                if isinstance(nested, list):
                    normalized = dict(value)
                    normalized["secrets"] = nested
                    return normalized

        return value


class EnvironmentSecretsStats(BaseModel):
    environment_id: str | None = None
    environment_name: str | None = None
    secret_count: int = 0
    last_updated_at: str | None = None
    last_activity_at: str | None = None


class SecretsStats(BaseModel):
    project_id: str | None = None
    total_secret_count: int = 0
    environments: list[EnvironmentSecretsStats] = Field(default_factory=list)
    generated_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)

        if "total_secret_count" not in normalized:
            for key in ("total_count", "count", "total", "secret_count", "secrets_count", "total_secrets"):
                raw_total = normalized.get(key)
                if isinstance(raw_total, int):
                    normalized["total_secret_count"] = raw_total
                    break

        if "environments" not in normalized:
            raw_env_counts = normalized.get("per_environment")
            if isinstance(raw_env_counts, dict):
                normalized["environments"] = [
                    {"environment_name": environment_name, "secret_count": secret_count}
                    for environment_name, secret_count in raw_env_counts.items()
                ]

        if "generated_at" not in normalized:
            for key in ("last_activity_at", "updated_at", "retrieved_at", "last_updated_at"):
                raw_generated_at = normalized.get(key)
                if isinstance(raw_generated_at, str):
                    normalized["generated_at"] = raw_generated_at
                    break

        return normalized


class PushSecretsRequest(BaseModel):
    secrets: dict[str, str]


class PushSecretsResponse(BaseModel):
    changed: int = 0
    unchanged: int = 0
    changed_keys: list[str] = Field(default_factory=list)
    unchanged_keys: list[str] = Field(default_factory=list)


class PullSecretsResponse(BaseModel):
    environment_id: str | None = None
    environment_name: str | None = None
    secrets: dict[str, str] = Field(default_factory=dict)


class CreateSecretRequest(BaseModel):
    key: str
    value: str


class UpdateSecretRequest(BaseModel):
    value: str


class MemberSummary(BaseModel):
    user_id: str | None = None
    email: str
    role: str | None = None
    secret_access: bool | None = None
    joined_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if "secret_access" not in normalized and "can_push_pull_secrets" in normalized:
            normalized["secret_access"] = normalized["can_push_pull_secrets"]
        return normalized


class InviteMemberRequest(BaseModel):
    email: str


class MemberAccessRequest(BaseModel):
    email: str
    can_push_pull_secrets: bool


class RevokeMemberRequest(BaseModel):
    email: str
    shared_token_action: str | None = None


class RuntimeTokenSummary(BaseModel):
    id: str
    name: str
    environment_id: str | None = None
    environment_name: str | None = None
    expires_at: str | None = None
    created_at: str | None = None
    last_used_at: str | None = None
    active: bool = True


class CreateRuntimeTokenRequest(BaseModel):
    name: str
    environment_id: str
    expires_in: str | None = None


class CreateRuntimeTokenResponse(BaseModel):
    token: str
    metadata: RuntimeTokenSummary

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if "token" in value and "metadata" in value:
            return value

        normalized = dict(value)
        token_value: str | None = None

        for key in ("plaintext_token", "plain_text_token", "raw_token", "token_value", "value", "secret"):
            candidate = normalized.pop(key, None)
            if isinstance(candidate, str) and candidate:
                token_value = candidate
                break

        metadata = normalized.pop("runtime_token", None)
        if not isinstance(metadata, dict):
            metadata = normalized

        if token_value is not None:
            return {"token": token_value, "metadata": metadata}

        return value


class PlaintextTokenResponse(BaseModel):
    token: str

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if "token" in value:
            return value

        for key in ("plaintext_token", "plain_text_token", "raw_token", "token_value", "value", "secret"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return {"token": candidate}

        return value


class TokenByNameRequest(BaseModel):
    name: str


class ShareTokenRequest(BaseModel):
    email: str


class TokenShareSummary(BaseModel):
    email: str
    shared_at: str | None = None
    shared_by: str | None = None


class AuditLogEntry(BaseModel):
    id: str
    actor: str | None = None
    action: str
    environment: str | None = None
    created_at: str
