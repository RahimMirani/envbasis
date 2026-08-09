from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from envbasis_cli.client import APIError
from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import (
    Endpoint,
    HistoricalSecret,
    RecoveryResult,
    SecretRetention,
    SecretRollbackResult,
    SecretVersionList,
    build_path,
)

app = typer.Typer(help="Inspect and recover secret versions.")
retention_app = typer.Typer(help="Configure secret-version archival.")


@app.command("list")
def list_history(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
    path: Annotated[str, typer.Option("--path")] = "/",
    include_archived: Annotated[bool, typer.Option("--archived/--no-archived")] = True,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        history = client.request_model(
            "GET",
            build_path(
                Endpoint.SECRET_VERSIONS,
                project_id=project.id,
                environment_id=environment.id,
                key=key,
            ),
            SecretVersionList,
            params={"path": path, "include_archived": include_archived},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(history.model_dump())
        return
    app_context.output.table(
        f"History: {path}:{key}",
        ["Version", "Updated", "Actor", "State", "Archived"],
        [
            [
                str(item.version),
                item.updated_at,
                item.updated_by_email or "-",
                "deleted" if item.is_deleted else "reference" if item.is_reference else "value",
                item.archived_at or "-",
            ]
            for item in history.versions
        ],
    )


@app.command("reveal")
def reveal_history(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
    version: Annotated[int, typer.Argument(min=1)],
    path: Annotated[str, typer.Option("--path")] = "/",
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        secret = client.request_model(
            "GET",
            build_path(
                Endpoint.SECRET_VERSION_REVEAL,
                project_id=project.id,
                environment_id=environment.id,
                key=key,
                version=str(version),
            ),
            HistoricalSecret,
            params={"path": path},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(secret.model_dump())
        return
    app_context.output.write(secret.value, end="\n")


@app.command("rollback")
def rollback_history(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
    version: Annotated[int, typer.Argument(min=1)],
    path: Annotated[str, typer.Option("--path")] = "/",
    yes: Annotated[bool, typer.Option("--yes", help="Apply without confirmation.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    if not yes:
        if app_context.options.output_json:
            app_context.output.error("JSON mode requires --yes for rollback.")
            raise typer.Exit(code=1)
        if not typer.confirm(f"Roll back {path}:{key} to version {version}?", default=False):
            raise typer.Exit(code=1)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        result = client.request_model(
            "POST",
            build_path(
                Endpoint.SECRET_VERSION_ROLLBACK,
                project_id=project.id,
                environment_id=environment.id,
                key=key,
                version=str(version),
            ),
            SecretRollbackResult,
            params={"path": path},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(result.model_dump())
        return
    app_context.output.success(f"Created version {result.version} from version {result.source_version}")


@app.command("recover")
def recover(
    ctx: typer.Context,
    at: Annotated[str, typer.Option("--at", help="ISO-8601 recovery timestamp.")],
    path: Annotated[str, typer.Option("--path")] = "/",
    recursive: Annotated[bool, typer.Option("--recursive")] = False,
    project_wide: Annotated[bool, typer.Option("--project-wide")] = False,
    apply: Annotated[bool, typer.Option("--apply", help="Create recovery versions; default is dry-run.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        app_context.output.error("--at must be a valid ISO-8601 timestamp.")
        raise typer.Exit(code=1) from exc
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        if project_wide:
            endpoint = build_path(Endpoint.PROJECT_RECOVERY, project_id=project.id)
        else:
            environment = resolve_environment(app_context, client, project)
            endpoint = build_path(
                Endpoint.ENVIRONMENT_RECOVERY,
                project_id=project.id,
                environment_id=environment.id,
            )
        result = client.request_model(
            "POST",
            endpoint,
            RecoveryResult,
            json_body={"at": at, "path": path, "recursive": recursive, "dry_run": not apply},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(result.model_dump())
        return
    verb = "Would change" if result.dry_run else "Recovered"
    app_context.output.info(f"{verb} {result.changed} secret(s) across {result.environments_changed} environment(s).")


@retention_app.command("show")
def show_retention(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        policy = client.request_model(
            "GET", build_path(Endpoint.SECRET_RETENTION, project_id=project.id), SecretRetention
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(policy.model_dump())
        return
    app_context.output.table(
        "Secret Retention",
        ["Retained versions", "Retain days", "Archive deleted after"],
        [[str(policy.retain_versions), str(policy.retain_days or "-"), str(policy.archive_deleted_after_days if policy.archive_deleted_after_days is not None else "-")]],
    )


@retention_app.command("set")
def set_retention(
    ctx: typer.Context,
    versions: Annotated[int, typer.Option("--versions", min=1, max=1000)],
    days: Annotated[int | None, typer.Option("--days", min=1, max=3650)] = None,
    archive_deleted_after: Annotated[int | None, typer.Option("--archive-deleted-after", min=0, max=3650)] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        policy = client.request_model(
            "PATCH",
            build_path(Endpoint.SECRET_RETENTION, project_id=project.id),
            SecretRetention,
            json_body={
                "retain_versions": versions,
                "retain_days": days,
                "archive_deleted_after_days": archive_deleted_after,
            },
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(policy.model_dump())
        return
    app_context.output.success("Updated secret retention policy")
