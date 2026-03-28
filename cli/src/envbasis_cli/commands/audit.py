from __future__ import annotations

import typer

from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_project
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import AuditLogEntry, Endpoint, build_path


app = typer.Typer(help="View project audit logs.")


@app.command("logs")
def audit_logs(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        logs = client.request_model(
            "GET",
            build_path(Endpoint.AUDIT_LOGS, project_id=project.id),
            list[AuditLogEntry],
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([entry.model_dump() for entry in logs])
        return

    if not logs:
        app_context.output.info(f"No audit logs found for project {project.name}.")
        return

    rows = [
        [
            entry.actor or "-",
            entry.action,
            entry.environment or "-",
            entry.created_at,
        ]
        for entry in logs
    ]
    app_context.output.table("Audit Logs", ["Actor", "Action", "Environment", "Created At"], rows)
