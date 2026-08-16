from typing import Annotated, Literal

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PRODUCTION_ENV_NAMES = {"production", "prod"}


class Settings(BaseSettings):
    app_name: str = "EnvBasis API"
    app_env: str = "development"
    debug: bool = Field(default=False, validation_alias="ENVBASIS_DEBUG")
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    database_url: str
    sql_echo: bool = False
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_algorithm: str = "HS256"
    supabase_jwt_audience: str | None = "authenticated"
    secrets_master_key: str | None = None
    secrets_root_key_provider: Literal["local", "aws_kms"] = "local"
    aws_kms_key_id: str | None = None
    aws_kms_region: str | None = None
    aws_kms_endpoint_url: str | None = None
    runtime_token_prefix: str = "envb_rt_"
    runtime_token_bytes: int = 32
    machine_auth_jwt_secret: str | None = None
    machine_auth_jwt_algorithm: Literal["HS256"] = "HS256"
    machine_auth_jwt_issuer: str = "envbasis-machine-auth"
    machine_auth_jwt_audience: str = "envbasis-machine"
    machine_auth_default_access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    machine_auth_min_access_token_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    machine_auth_max_access_token_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    machine_auth_client_id_bytes: int = Field(default=18, ge=12, le=64)
    machine_auth_client_secret_bytes: int = Field(default=48, ge=32, le=128)
    machine_auth_max_failed_attempts: int = Field(default=5, ge=2, le=50)
    machine_auth_lockout_seconds: int = Field(default=900, ge=60, le=86400)
    machine_auth_default_rotation_overlap_seconds: int = Field(default=0, ge=0, le=604800)
    proxy_service_token: str | None = None
    webhooks_enabled: bool = False
    webhook_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    webhook_max_attempts: int = Field(default=5, ge=1, le=20)
    webhook_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    webhook_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)
    webhook_worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    webhook_worker_batch_size: int = Field(default=25, ge=1, le=250)
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    redis_key_prefix: str = "envbasis"
    redis_socket_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    api_idempotency_encryption_key: str | None = None
    api_idempotency_retention_seconds: int = Field(default=86400, ge=300, le=604800)
    api_idempotency_pending_seconds: int = Field(default=300, ge=30, le=3600)
    api_version: str = "1"
    api_deprecation_sunset: str = "Wed, 01 Jul 2027 00:00:00 GMT"
    rate_limit_auth_requests: int = 120
    rate_limit_auth_window_seconds: int = 60
    rate_limit_secret_requests: int = 300
    rate_limit_secret_window_seconds: int = 3600
    rate_limit_runtime_requests: int = 10000
    rate_limit_runtime_window_seconds: int = 3600
    rate_limit_general_requests: int = 1000
    rate_limit_general_window_seconds: int = 3600
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
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
    invite_app_base_url: str = "http://localhost:5173"
    invite_logo_url: str | None = None
    invite_from_email: str | None = None
    invite_smtp_host: str | None = None
    invite_smtp_port: int = 587
    invite_smtp_user: str | None = None
    invite_smtp_password: str | None = None
    invite_smtp_use_tls: bool = True

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: str | list[str] | None) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [origin.strip() for origin in value if origin and origin.strip()]
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @field_validator("api_idempotency_encryption_key")
    @classmethod
    def validate_idempotency_encryption_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            Fernet(value.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "API_IDEMPOTENCY_ENCRYPTION_KEY must be a valid Fernet key."
            ) from exc
        return value

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
            raise ValueError("DATABASE_URL must point to Supabase Postgres, not a local database.")

        if not (
            self.machine_auth_min_access_token_ttl_seconds
            <= self.machine_auth_default_access_token_ttl_seconds
            <= self.machine_auth_max_access_token_ttl_seconds
        ):
            raise ValueError(
                "Machine access-token TTL must satisfy minimum <= default <= maximum."
            )

        if self.webhook_retry_base_seconds > self.webhook_retry_max_seconds:
            raise ValueError(
                "Webhook retry delay must satisfy base seconds <= maximum seconds."
            )

        if self.app_env.lower() not in PRODUCTION_ENV_NAMES:
            return self

        if self.debug:
            raise ValueError("ENVBASIS_DEBUG must be false in production.")
        if not self.supabase_jwt_secret or self.supabase_jwt_secret == "replace-me":
            raise ValueError("SUPABASE_JWT_SECRET must be set to a real value in production.")
        if self.secrets_root_key_provider == "local":
            if not self.secrets_master_key or self.secrets_master_key == "replace-with-fernet-key":
                raise ValueError("SECRETS_MASTER_KEY must be set to a real value in production.")
        elif not self.aws_kms_key_id:
            raise ValueError("AWS_KMS_KEY_ID is required when SECRETS_ROOT_KEY_PROVIDER=aws_kms.")
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
        if not self.machine_auth_jwt_secret or self.machine_auth_jwt_secret == "replace-me":
            raise ValueError("MACHINE_AUTH_JWT_SECRET must be set to a real value in production.")
        if not self.proxy_service_token or self.proxy_service_token == "replace-me":
            raise ValueError("PROXY_SERVICE_TOKEN must be set to a real value in production.")
        if self.rate_limit_backend != "redis" or not self.redis_url:
            raise ValueError(
                "Production requires RATE_LIMIT_BACKEND=redis and a REDIS_URL."
            )
        if not self.api_idempotency_encryption_key:
            raise ValueError(
                "API_IDEMPOTENCY_ENCRYPTION_KEY is required in production."
            )

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
