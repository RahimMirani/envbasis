from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    app_name: str = "EnvBasis Agent Proxy"
    app_env: str = "development"

    machine_auth_jwt_secret: SecretStr
    machine_auth_jwt_algorithm: Literal["HS256"] = "HS256"
    machine_auth_jwt_issuer: str = "envbasis-machine-auth"
    machine_auth_jwt_audience: str = "envbasis-machine"

    openai_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    openai_upstream_url: str = "https://api.openai.com"
    github_upstream_url: str = "https://api.github.com"
    upstream_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    max_request_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_response_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @field_validator("openai_upstream_url", "github_upstream_url")
    @classmethod
    def validate_upstream_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("Provider upstream URLs must use HTTPS.")
        return normalized

    @model_validator(mode="after")
    def validate_production_upstreams(self) -> "ProxySettings":
        if self.app_env.lower() in {"production", "prod"}:
            if self.openai_upstream_url != "https://api.openai.com":
                raise ValueError("Production OpenAI upstream must be https://api.openai.com.")
            if self.github_upstream_url != "https://api.github.com":
                raise ValueError("Production GitHub upstream must be https://api.github.com.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> ProxySettings:
    return ProxySettings()

