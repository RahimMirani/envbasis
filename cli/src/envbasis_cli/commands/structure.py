from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.client import APIError
from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import (
    Endpoint,
    ProjectSecretTag,
    SecretFolder,
    SecretFolderListResponse,
    build_path,
)

folders_app = typer.Typer(help="Navigate and manage secret folders.")
tags_app = typer.Typer(help="Manage the project secret-tag catalogue.")


@folders_app.command("list")
def list_folders(
    ctx: typer.Context,
    path: Annotated[str, typer.Option("--path", help="Parent folder path.")] = "/",
    recursive: Annotated[bool, typer.Option("--recursive", help="Include all descendants.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        response = client.request_model(
            "GET",
            build_path(Endpoint.SECRET_FOLDERS, project_id=project.id, environment_id=environment.id),
            SecretFolderListResponse,
            params={"path": path, "recursive": recursive},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(response.model_dump())
        return
    if not response.folders:
        app_context.output.info(f"No folders below {response.path}.")
        return
    app_context.output.table(
        "Secret Folders",
        ["Path", "Parent", "Description"],
        [[folder.path, folder.parent_path, folder.description or "-"] for folder in response.folders],
    )


@folders_app.command("create")
def create_folder(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Folder path, for example /backend/payments.")],
    description: Annotated[str | None, typer.Option("--description")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        folder = client.request_model(
            "POST",
            build_path(Endpoint.SECRET_FOLDERS, project_id=project.id, environment_id=environment.id),
            SecretFolder,
            json_body={"path": path, **({"description": description} if description else {})},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(folder.model_dump())
        return
    app_context.output.success(f"Created folder {folder.path}")


@folders_app.command("delete")
def delete_folder(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Folder path to delete.")],
    recursive: Annotated[bool, typer.Option("--recursive", help="Delete empty descendants too.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        client.request(
            "DELETE",
            build_path(Endpoint.SECRET_FOLDERS, project_id=project.id, environment_id=environment.id),
            params={"path": path, "recursive": recursive},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json({"deleted": True, "path": path})
        return
    app_context.output.success(f"Deleted folder {path}")


@tags_app.command("list")
def list_tags(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        tags = client.request_model(
            "GET",
            build_path(Endpoint.SECRET_TAGS, project_id=project.id),
            list[ProjectSecretTag],
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json([tag.model_dump() for tag in tags])
        return
    app_context.output.table(
        "Secret Tags", ["Name", "Color", "Description"],
        [[tag.name, tag.color or "-", tag.description or "-"] for tag in tags],
    )


@tags_app.command("create")
def create_tag(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Tag name.")],
    color: Annotated[str | None, typer.Option("--color")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        tag = client.request_model(
            "POST",
            build_path(Endpoint.SECRET_TAGS, project_id=project.id),
            ProjectSecretTag,
            json_body={
                "name": name,
                **({"color": color} if color else {}),
                **({"description": description} if description else {}),
            },
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(tag.model_dump())
        return
    app_context.output.success(f"Created tag {tag.name}")


@tags_app.command("update")
def update_tag(
    ctx: typer.Context,
    tag_id: Annotated[str, typer.Argument(help="Tag ID.")],
    color: Annotated[str | None, typer.Option("--color")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        tag = client.request_model(
            "PATCH",
            build_path(Endpoint.SECRET_TAG_DETAIL, project_id=project.id, tag_id=tag_id),
            ProjectSecretTag,
            json_body={"color": color, "description": description},
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json(tag.model_dump())
        return
    app_context.output.success(f"Updated tag {tag.name}")


@tags_app.command("delete")
def delete_tag(
    ctx: typer.Context,
    tag_id: Annotated[str, typer.Argument(help="Tag ID.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)
    try:
        project = resolve_project(app_context, client)
        client.request(
            "DELETE",
            build_path(Endpoint.SECRET_TAG_DETAIL, project_id=project.id, tag_id=tag_id),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc
    if app_context.options.output_json:
        app_context.output.emit_json({"deleted": True, "tag_id": tag_id})
        return
    app_context.output.success(f"Deleted tag {tag_id}")
