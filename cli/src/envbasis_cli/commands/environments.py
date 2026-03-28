from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.command_support import (
    build_client,
    exit_for_api_error,
    fetch_environments,
    persist_local_config,
    resolve_environment,
    resolve_project,
)
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import CreateEnvironmentRequest, Endpoint, EnvironmentSummary, build_path


app = typer.Typer(name="env", help="List and manage project environments.")


@app.command("list")
def list_environments(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environments = fetch_environments(client, project.id)
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([environment.model_dump() for environment in environments])
        return

    if not environments:
        app_context.output.info(f"No environments found for project {project.name}.")
        return

    rows = [
        [environment.name, environment.created_at or "-", environment.updated_at or "-"]
        for environment in environments
    ]
    app_context.output.table("Environments", ["Name", "Created", "Updated"], rows)


@app.command("create")
def create_environment(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Environment name.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        request = CreateEnvironmentRequest(name=name)
        environment = client.request_model(
            "POST",
            build_path(Endpoint.ENVIRONMENTS, project_id=project.id),
            EnvironmentSummary,
            json_body=request.model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(environment.model_dump())
        return

    app_context.output.success(f"Created environment {environment.name}")


@app.command("use")
def use_environment(
    ctx: typer.Context,
    environment_reference: Annotated[str, typer.Argument(help="Environment name or ID.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(
            app_context,
            client,
            project,
            reference=environment_reference,
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    persist_local_config(app_context, environment=environment.name)

    if app_context.options.output_json:
        app_context.output.emit_json(
            {
                "selected": True,
                "environment": environment.name,
                "environment_id": environment.id,
            }
        )
        return

    app_context.output.success(f"Selected environment {environment.name}")
