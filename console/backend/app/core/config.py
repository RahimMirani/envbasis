from typing import Annotated

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PRODUCTION_ENV_NAMES = {"production", "prod"}


class Settings(BaseSettings):
    app_name: str = "EnvBasis API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    database_url: str
    sql_echo: bool = False
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_algorithm: str = "HS256"
    supabase_jwt_audience: str | None = "authenticated"
    secrets_master_key: str | None = None
    runtime_token_prefix: str = "envb_rt_"
    runtime_token_bytes: int = 32
    rate_limit_auth_requests: int = 120
    rate_limit_auth_window_seconds: int = 60
    rate_limit_secret_requests: int = 300
    rate_limit_secret_window_seconds: int = 3600
    rate_limit_runtime_requests: int = 10000
    rate_limit_runtime_window_seconds: int = 3600
    rate_limit_general_requests: int = 1000
    rate_limit_general_window_seconds: int = 3600
    audit_log_retention_days: int = 90
    audit_log_cleanup_interval_seconds: int = 86400
    cli_auth_verification_url: str = "http://localhost:3000/cli"
    cli_auth_device_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    cli_auth_poll_interval_seconds: int = Field(default=5, ge=1, le=30)
    cli_auth_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    cli_auth_refresh_token_ttl_seconds: int = Field(default=2592000, ge=3600, le=31536000)
    cli_auth_device_code_bytes: int = Field(default=48, ge=16, le=128)
    cli_auth_refresh_token_bytes: int = Field(default=48, ge=16, le=128)
    cli_auth_jwt_secret: str | None = None
    cli_auth_jwt_algorithm: str = "HS256"
    cli_auth_jwt_issuer: str = "envbasis-cli"
    cli_auth_jwt_audience: str = "envbasis-cli"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: str | list[str] | None) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [origin.strip() for origin in value if origin and origin.strip()]
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
            raise ValueError("DATABASE_URL must point to Supabase Postgres, not a local database.")

        if self.app_env.lower() not in PRODUCTION_ENV_NAMES:
            return self

        if self.debug:
            raise ValueError("DEBUG must be false in production.")
        if not self.supabase_jwt_secret or self.supabase_jwt_secret == "replace-me":
            raise ValueError("SUPABASE_JWT_SECRET must be set to a real value in production.")
        if not self.secrets_master_key or self.secrets_master_key == "replace-with-fernet-key":
            raise ValueError("SECRETS_MASTER_KEY must be set to a real value in production.")
        if (
            "postgres:postgres@" in self.database_url
            or "db.<project-ref>.supabase.co" in self.database_url
        ):
            raise ValueError("DATABASE_URL must point to the real production Supabase database.")
        if not self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must be configured in production.")
        if "*" in self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS cannot contain '*' in production.")
        if not self.cli_auth_jwt_secret or self.cli_auth_jwt_secret == "replace-me":
            raise ValueError("CLI_AUTH_JWT_SECRET must be set to a real value in production.")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
