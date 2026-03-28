from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.command_support import (
    build_client,
    exit_for_api_error,
    persist_local_config,
    resolve_project,
)
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import (
    CreateProjectRequest,
    Endpoint,
    ProjectDetail,
    UpdateProjectRequest,
    build_path,
)

app = typer.Typer(help="Manage the active project.")


@app.command("create")
def create_project(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Project name.")],
    description: Annotated[str | None, typer.Option("--description", help="Project description.")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    request = CreateProjectRequest(name=name, description=description)

    try:
        project = client.request_model(
            "POST",
            build_path(Endpoint.PROJECTS),
            ProjectDetail,
            json_body=request.model_dump(exclude_none=True),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(project.model_dump())
        return

    app_context.output.success(f"Created project {project.name}")


@app.command("show")
def show_project(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        project_detail = client.request_model(
            "GET",
            build_path(Endpoint.PROJECT_DETAIL, project_id=project.id),
            ProjectDetail,
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(project_detail.model_dump())
        return

    rows = [
        ["id", project_detail.id],
        ["name", project_detail.name],
        ["description", project_detail.description or "-"],
        ["role", project_detail.role or "-"],
        ["environments", str(project_detail.environment_count or 0)],
        ["members", str(project_detail.member_count or 0)],
        ["tokens", str(project_detail.token_count or 0)],
        ["created_at", project_detail.created_at or "-"],
        ["updated_at", project_detail.updated_at or "-"],
    ]
    app_context.output.table("Project", ["Field", "Value"], rows)


@app.command("use")
def use_project(
    ctx: typer.Context,
    project_reference: Annotated[str, typer.Argument(help="Project name or ID.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client, reference=project_reference)
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    persist_local_config(
        app_context,
        project_id=project.id,
        project_name=project.name,
        environment=None,
    )

    if app_context.options.output_json:
        app_context.output.emit_json(
            {
                "selected": True,
                "project_id": project.id,
                "project_name": project.name,
            }
        )
        return

    app_context.output.success(f"Selected project {project.name}")


@app.command("update")
def update_project(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", help="Updated project name.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="Updated project description.")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    if name is None and description is None:
        app_context.output.error("Nothing to update. Pass --name and/or --description.")
        raise typer.Exit(code=1)

    try:
        project = resolve_project(app_context, client)
        request = UpdateProjectRequest(name=name, description=description)
        updated_project = client.request_model(
            "PATCH",
            build_path(Endpoint.PROJECT_DETAIL, project_id=project.id),
            ProjectDetail,
            json_body=request.model_dump(exclude_none=True),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.local_config.project_id == updated_project.id:
        persist_local_config(
            app_context,
            project_id=updated_project.id,
            project_name=updated_project.name,
        )

    if app_context.options.output_json:
        app_context.output.emit_json(updated_project.model_dump())
        return

    app_context.output.success(f"Updated project {updated_project.name}")
