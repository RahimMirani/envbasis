from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    app_name: str = "EnvBasis Agent Proxy"
    app_env: str = "development"

    machine_auth_jwt_secret: SecretStr
    machine_auth_jwt_algorithm: Literal["HS256"] = "HS256"
    machine_auth_jwt_issuer: str = "envbasis-machine-auth"
    machine_auth_jwt_audience: str = "envbasis-machine"

    control_plane_url: str | None = None
    proxy_service_token: SecretStr | None = None

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    openai_upstream_url: str = "https://api.openai.com"
    anthropic_upstream_url: str = "https://api.anthropic.com"
    github_upstream_url: str = "https://api.github.com"
    upstream_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    max_request_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_response_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @field_validator("openai_upstream_url", "anthropic_upstream_url", "github_upstream_url")
    @classmethod
    def validate_upstream_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("Provider upstream URLs must use HTTPS.")
        return normalized

    @field_validator("control_plane_url")
    @classmethod
    def validate_control_plane_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.rstrip("/")
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CONTROL_PLANE_URL must be an absolute HTTP(S) URL.")
        return normalized

    @model_validator(mode="after")
    def validate_production_upstreams(self) -> "ProxySettings":
        if self.control_plane_url and self.proxy_service_token is None:
            raise ValueError("PROXY_SERVICE_TOKEN is required when CONTROL_PLANE_URL is set.")
        if self.proxy_service_token is not None and not self.control_plane_url:
            raise ValueError("CONTROL_PLANE_URL is required when PROXY_SERVICE_TOKEN is set.")
        if self.app_env.lower() in {"production", "prod"}:
            if self.openai_upstream_url != "https://api.openai.com":
                raise ValueError("Production OpenAI upstream must be https://api.openai.com.")
            if self.anthropic_upstream_url != "https://api.anthropic.com":
                raise ValueError("Production Anthropic upstream must be https://api.anthropic.com.")
            if self.github_upstream_url != "https://api.github.com":
                raise ValueError("Production GitHub upstream must be https://api.github.com.")
            if self.control_plane_url and not self.control_plane_url.startswith("https://"):
                raise ValueError("Production CONTROL_PLANE_URL must use HTTPS.")
        return self

    @property
    def uses_control_plane(self) -> bool:
        return self.control_plane_url is not None and self.proxy_service_token is not None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> ProxySettings:
    return ProxySettings()
