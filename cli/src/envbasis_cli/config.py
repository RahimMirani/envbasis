from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, ValidationError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


CONFIG_FILENAME = ".envbasis.toml"
API_URL_ENV_VAR = "ENVBASIS_API_URL"
CURRENT_CONFIG_VERSION = 1

DEFAULT_API_BASE_URL = "https://api.envbasis.com/api/v1"


def normalize_api_base_url(value: str) -> str:
    """Validate and normalize an EnvBasis API base URL."""
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API URL must be a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("API URL must not contain a username or password.")
    if parsed.query or parsed.fragment:
        raise ValueError("API URL must not contain a query string or fragment.")

    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", ""))


class LocalConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_version: int = CURRENT_CONFIG_VERSION
    api_base_url: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    environment: str | None = None


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationResult:
    migrated: bool
    old_version: int
    new_version: int
    config_path: Path
    backup_path: Path | None = None


class ConfigManager:
    def __init__(self, path: Path | None = None, *, start_dir: Path | None = None) -> None:
        if path is not None:
            self.path = path
            return

        search_from = (start_dir or Path.cwd()).resolve()
        self.path = self._discover(search_from) or search_from / CONFIG_FILENAME

    def load(self) -> LocalConfig:
        if not self.path.exists():
            return LocalConfig()

        raw_data = self._read_raw()
        version = self._read_version(raw_data)
        if version > CURRENT_CONFIG_VERSION:
            raise ConfigError(
                f"Configuration version {version} is newer than this CLI supports "
                f"(maximum {CURRENT_CONFIG_VERSION}). Upgrade the EnvBasis CLI."
            )

        versioned_data = dict(raw_data)
        versioned_data["config_version"] = version
        try:
            return LocalConfig.model_validate(versioned_data)
        except ValidationError as exc:
            raise ConfigError(f"Invalid configuration in {self.path}: {exc}") from exc

    def save(self, config: LocalConfig) -> None:
        lines = []
        for field_name, value in config.model_dump().items():
            if value is None:
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                lines.append(f"{field_name} = {value}")
                continue
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{field_name} = "{escaped}"')
        content = "\n".join(lines) + ("\n" if lines else "")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file_obj:
                file_obj.write(content)
                file_obj.flush()
                os.fsync(file_obj.fileno())
                temporary_path = Path(file_obj.name)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ConfigError(f"Could not save configuration to {self.path}: {exc}") from exc

    def migrate(self) -> MigrationResult:
        if not self.path.exists():
            raise ConfigError(f"No configuration file found at {self.path}. Run envbasis init first.")

        config = self.load()
        old_version = config.config_version
        if old_version == CURRENT_CONFIG_VERSION:
            return MigrationResult(
                migrated=False,
                old_version=old_version,
                new_version=old_version,
                config_path=self.path,
            )

        migrated_data = config.model_dump()
        migrated_data["config_version"] = CURRENT_CONFIG_VERSION
        try:
            migrated_config = LocalConfig.model_validate(migrated_data)
        except ValidationError as exc:  # pragma: no cover - guarded by load and migration steps
            raise ConfigError(f"Could not migrate configuration: {exc}") from exc

        backup_path = self._next_backup_path(old_version)
        try:
            shutil.copy2(self.path, backup_path)
            os.chmod(backup_path, 0o600)
        except OSError as exc:
            raise ConfigError(f"Could not create configuration backup at {backup_path}: {exc}") from exc

        self.save(migrated_config)
        return MigrationResult(
            migrated=True,
            old_version=old_version,
            new_version=CURRENT_CONFIG_VERSION,
            config_path=self.path,
            backup_path=backup_path,
        )

    def _read_raw(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as file_obj:
                return tomllib.load(file_obj)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Could not read configuration from {self.path}: {exc}") from exc

    @staticmethod
    def _read_version(raw_data: dict[str, Any]) -> int:
        value = raw_data.get("config_version", 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError("config_version must be a non-negative integer.")
        return value

    @staticmethod
    def _discover(start_dir: Path) -> Path | None:
        for directory in (start_dir, *start_dir.parents):
            candidate = directory / CONFIG_FILENAME
            if candidate.is_file():
                return candidate
        return None

    def _next_backup_path(self, old_version: int) -> Path:
        base = self.path.with_name(f"{self.path.name}.v{old_version}.bak")
        if not base.exists():
            return base

        index = 1
        while True:
            candidate = self.path.with_name(f"{self.path.name}.v{old_version}.bak.{index}")
            if not candidate.exists():
                return candidate
            index += 1
