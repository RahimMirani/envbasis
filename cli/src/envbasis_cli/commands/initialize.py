from __future__ import annotations

from typing import Annotated, TypeVar

import typer
from pydantic import BaseModel

from envbasis_cli.client import APIError, EnvBasisClient
from envbasis_cli.command_support import exit_for_api_error, fetch_environments, fetch_projects
from envbasis_cli.config import LocalConfig, normalize_api_base_url
from envbasis_cli.context import AppContext, require_app_context
from envbasis_cli.contracts import Endpoint, EnvironmentSummary, ProjectSummary, UserProfile, build_path


Selectable = TypeVar("Selectable", bound=BaseModel)


def register(app: typer.Typer) -> None:
    @app.command("init")
    def initialize(
        ctx: typer.Context,
        api_url: Annotated[
            str | None,
            typer.Option("--api-url", help="EnvBasis API URL, including its API base path."),
        ] = None,
        project_reference: Annotated[
            str | None,
            typer.Option("--project", help="Project name or ID to select."),
        ] = None,
        environment_reference: Annotated[
            str | None,
            typer.Option("--env", help="Environment name or ID to select."),
        ] = None,
        no_input: Annotated[
            bool,
            typer.Option("--no-input", help="Never prompt; fail when a selection is required."),
        ] = False,
    ) -> None:
        app_context = require_app_context(ctx)
        interactive = not no_input and not app_context.options.output_json

        selected_api_url = _select_api_url(app_context, api_url, interactive=interactive)
        client = EnvBasisClient(selected_api_url, app_context.auth_manager)

        try:
            user = client.request_model("GET", build_path(Endpoint.AUTH_ME), UserProfile)
            projects = fetch_projects(client)
            project = _select_item(
                app_context,
                projects,
                label="project",
                reference=project_reference or app_context.resolved_project,
                interactive=interactive,
            )
            environments = fetch_environments(client, project.id)
            environment = _select_item(
                app_context,
                environments,
                label="environment",
                reference=environment_reference or app_context.resolved_environment,
                interactive=interactive,
            )
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        config = LocalConfig(
            api_base_url=selected_api_url,
            project_id=project.id,
            project_name=project.name,
            environment=environment.name,
        )
        app_context.config_manager.save(config)
        app_context.local_config = config

        payload = {
            "configured": True,
            "api_url": selected_api_url,
            "user": user.model_dump(),
            "project_id": project.id,
            "project_name": project.name,
            "environment_id": environment.id,
            "environment": environment.name,
            "config_path": str(app_context.config_manager.path),
        }
        if app_context.options.output_json:
            app_context.output.emit_json(payload)
            return

        app_context.output.success(f"Initialized EnvBasis for {project.name}/{environment.name}")
        app_context.output.info(f"Configuration saved to {app_context.config_manager.path}")


def _select_api_url(app_context: AppContext, option_value: str | None, *, interactive: bool) -> str:
    candidate = option_value or app_context.resolved_api_url
    if interactive and option_value is None and app_context.options.api_url is None:
        candidate = typer.prompt("EnvBasis API URL", default=candidate)

    try:
        return normalize_api_base_url(candidate)
    except ValueError as exc:
        app_context.output.error(str(exc))
        raise typer.Exit(code=1) from exc


def _select_item(
    app_context: AppContext,
    items: list[Selectable],
    *,
    label: str,
    reference: str | None,
    interactive: bool,
) -> Selectable:
    if not items:
        app_context.output.error(f"No {label}s are available for this account.")
        raise typer.Exit(code=1)

    if reference:
        matches = [item for item in items if item.id == reference or item.name == reference]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            app_context.output.error(f'{label.title()} reference "{reference}" is ambiguous. Use its ID.')
            raise typer.Exit(code=1)
        app_context.output.error(f'{label.title()} "{reference}" was not found.')
        raise typer.Exit(code=1)

    if len(items) == 1:
        return items[0]

    if not interactive:
        option_name = "--project" if label == "project" else "--env"
        app_context.output.error(f"Multiple {label}s are available. Select one with {option_name}.")
        raise typer.Exit(code=1)

    app_context.output.table(
        f"Select a {label}",
        ["Number", "Name", "ID"],
        [[str(index), item.name, item.id] for index, item in enumerate(items, start=1)],
    )
    choice = typer.prompt(
        f"{label.title()} number",
        type=int,
    )
    if choice < 1 or choice > len(items):
        app_context.output.error(f"Choose a number between 1 and {len(items)}.")
        raise typer.Exit(code=1)
    return items[choice - 1]
