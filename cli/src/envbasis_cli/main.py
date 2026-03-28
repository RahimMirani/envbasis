from __future__ import annotations

import os
from typing import Annotated

import typer

from envbasis_cli.auth import TokenStore
from envbasis_cli.commands import audit, auth, environments, members, project, projects, secrets, tokens
from envbasis_cli.config import API_URL_ENV_VAR, ConfigManager
from envbasis_cli.context import AppContext, GlobalOptions, require_app_context
from envbasis_cli.output import OutputManager


app = typer.Typer(
    name="envbasis",
    help="Thin authenticated CLI for the EnvBasis backend API.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(projects.app, name="projects")
app.add_typer(project.app, name="project")
app.add_typer(environments.app, name="env")
app.add_typer(secrets.app, name="secrets")
app.add_typer(members.app, name="members")
app.add_typer(tokens.app, name="token")
app.add_typer(audit.app, name="audit")
auth.register(app)
secrets.register(app)
members.register(app)


@app.callback()
def main(
    ctx: typer.Context,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help=f"Override the backend API base URL. Env fallback: {API_URL_ENV_VAR}.",
        ),
    ] = None,
    project_name: Annotated[str | None, typer.Option("--project", help="Override the active project ID or name.")] = None,
    environment_name: Annotated[str | None, typer.Option("--env", help="Override the active environment name.")] = None,
    output_json: Annotated[bool, typer.Option("--json", help="Emit JSON output for scripting.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print verbose diagnostics.")] = False,
) -> None:
    config_manager = ConfigManager()
    local_config = config_manager.load()
    output = OutputManager(output_json=output_json, verbose=verbose)
    env_api_url = os.getenv(API_URL_ENV_VAR)

    ctx.obj = AppContext(
        options=GlobalOptions(
            api_url=api_url,
            env_api_url=env_api_url,
            project=project_name,
            environment=environment_name,
            output_json=output_json,
            verbose=verbose,
        ),
        config_manager=config_manager,
        local_config=local_config,
        auth_manager=TokenStore(),
        output=output,
    )


@app.command("context")
def show_context(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    payload = {
        "api_url": app_context.resolved_api_url,
        "project": app_context.resolved_project,
        "environment": app_context.resolved_environment,
        "json": app_context.options.output_json,
        "verbose": app_context.options.verbose,
    }

    if app_context.options.output_json:
        app_context.output.emit_json(payload)
        return

    app_context.output.table(
        "CLI Context",
        ["Field", "Value"],
        [[key, str(value)] for key, value in payload.items()],
    )


def run() -> None:
    app()
