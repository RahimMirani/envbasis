from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


CONFIG_FILENAME = ".envbasis.toml"
API_URL_ENV_VAR = "ENVBASIS_API_URL"

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"


class LocalConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_base_url: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    environment: str | None = None


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.cwd() / CONFIG_FILENAME

    def load(self) -> LocalConfig:
        if not self.path.exists():
            return LocalConfig()

        with self.path.open("rb") as file_obj:
            raw_data = tomllib.load(file_obj)
        return LocalConfig.model_validate(raw_data)

    def save(self, config: LocalConfig) -> None:
        lines = []
        for field_name, value in config.model_dump().items():
            if value is None:
                continue
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{field_name} = "{escaped}"')
        content = "\n".join(lines) + ("\n" if lines else "")
        self.path.write_text(content, encoding="utf-8")
