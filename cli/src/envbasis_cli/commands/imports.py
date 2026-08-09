from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.client import APIError
from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import Endpoint, SecretImportRule, build_path

app = typer.Typer(help="Manage deterministic secret imports between environments and folders.")


@app.command("list")
def list_imports(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        rules = client.request_model(
            "GET", build_path(Endpoint.SECRET_IMPORTS, project_id=project.id), list[SecretImportRule]
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json([rule.model_dump() for rule in rules])
        return
    app_context.output.table(
        "Secret Imports",
        ["ID", "Source", "Target", "Priority", "Enabled"],
        [
            [
                rule.id,
                f"{rule.source_environment_id}:{rule.source_path}",
                f"{rule.target_environment_id}:{rule.target_path}",
                str(rule.priority),
                "yes" if rule.enabled else "no",
            ]
            for rule in rules
        ],
    )


@app.command("create")
def create_import(
    ctx: typer.Context,
    source_environment: Annotated[str, typer.Option("--from-env", help="Source environment name or ID.")],
    source_path: Annotated[str, typer.Option("--from-path")] = "/",
    target_path: Annotated[str, typer.Option("--to-path")] = "/",
    target_environment: Annotated[str | None, typer.Option("--to-env", help="Target environment; defaults to active.")] = None,
    recursive: Annotated[bool, typer.Option("--recursive")] = False,
    priority: Annotated[int, typer.Option("--priority", min=-1000, max=1000)] = 0,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        source = resolve_environment(app_context, client, project, reference=source_environment)
        target = resolve_environment(app_context, client, project, reference=target_environment)
        rule = client.request_model(
            "POST",
            build_path(Endpoint.SECRET_IMPORTS, project_id=project.id),
            SecretImportRule,
            json_body={
                "source_environment_id": source.id,
                "source_path": source_path,
                "target_environment_id": target.id,
                "target_path": target_path,
                "recursive": recursive,
                "priority": priority,
                "enabled": True,
            },
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(rule.model_dump())
        return
    app_context.output.success(f"Created import {rule.id}")


@app.command("update")
def update_import(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="Import ID.")],
    priority: Annotated[int | None, typer.Option("--priority", min=-1000, max=1000)] = None,
    enabled: Annotated[bool | None, typer.Option("--enabled/--disabled")] = None,
    recursive: Annotated[bool | None, typer.Option("--recursive/--not-recursive")] = None,
) -> None:
    app_context = require_app_context(ctx)
    if priority is None and enabled is None and recursive is None:
        app_context.output.error("Provide at least one change.")
        raise typer.Exit(code=1)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        body = {
            key: value
            for key, value in {
                "priority": priority,
                "enabled": enabled,
                "recursive": recursive,
            }.items()
            if value is not None
        }
        rule = client.request_model(
            "PATCH",
            build_path(Endpoint.SECRET_IMPORT_DETAIL, project_id=project.id, import_id=import_id),
            SecretImportRule,
            json_body=body,
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(rule.model_dump())
        return
    app_context.output.success(f"Updated import {rule.id}")


@app.command("delete")
def delete_import(ctx: typer.Context, import_id: Annotated[str, typer.Argument(help="Import ID.")]) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        client.request(
            "DELETE",
            build_path(Endpoint.SECRET_IMPORT_DETAIL, project_id=project.id, import_id=import_id),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json({"deleted": True, "import_id": import_id})
        return
    app_context.output.success(f"Deleted import {import_id}")
