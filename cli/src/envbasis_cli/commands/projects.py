from __future__ import annotations

import typer

from envbasis_cli.command_support import build_client, exit_for_api_error, fetch_projects
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context


app = typer.Typer(help="List and manage projects.")


@app.command("list")
def list_projects(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        projects = fetch_projects(client)
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([project.model_dump() for project in projects])
        return

    if not projects:
        app_context.output.info("No projects found.")
        return

    rows = [
        [
            project.name,
            project.role or "-",
            str(project.environment_count or 0),
            str(project.member_count or 0),
            str(project.token_count or 0),
            project.last_activity_at or "-",
        ]
        for project in projects
    ]
    app_context.output.table(
        "Projects",
        ["Name", "Role", "Envs", "Members", "Tokens", "Last Activity"],
        rows,
    )
