from __future__ import annotations

from dataclasses import dataclass

import typer

from envbasis_cli.auth import AuthManager
from envbasis_cli.config import DEFAULT_API_BASE_URL, ConfigManager, LocalConfig
from envbasis_cli.output import OutputManager


@dataclass(slots=True)
class GlobalOptions:
    api_url: str | None
    env_api_url: str | None
    project: str | None
    environment: str | None
    output_json: bool
    verbose: bool


@dataclass(slots=True)
class AppContext:
    options: GlobalOptions
    config_manager: ConfigManager
    local_config: LocalConfig
    auth_manager: AuthManager
    output: OutputManager

    @property
    def resolved_api_url(self) -> str | None:
        return self.options.api_url or self.options.env_api_url or self.local_config.api_base_url or DEFAULT_API_BASE_URL

    @property
    def resolved_project(self) -> str | None:
        return self.options.project or self.local_config.project_id or self.local_config.project_name

    @property
    def resolved_environment(self) -> str | None:
        return self.options.environment or self.local_config.environment


def require_app_context(ctx: typer.Context) -> AppContext:
    context = ctx.obj
    if not isinstance(context, AppContext):
        raise typer.Exit(code=1)
    return context
