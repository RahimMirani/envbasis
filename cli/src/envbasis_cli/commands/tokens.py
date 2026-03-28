from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.command_support import (
    build_client,
    exit_for_api_error,
    fetch_environments,
    resolve_project,
)
from envbasis_cli.client import APIError, EnvBasisClient
from envbasis_cli.context import AppContext, require_app_context
from envbasis_cli.contracts import (
    CreateRuntimeTokenRequest,
    CreateRuntimeTokenResponse,
    Endpoint,
    PlaintextTokenResponse,
    RuntimeTokenSummary,
    ShareTokenRequest,
    TokenByNameRequest,
    TokenShareSummary,
    build_path,
)

app = typer.Typer(name="token", help="Manage runtime tokens.")


@app.command("list")
def list_tokens(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        tokens = _list_runtime_tokens(client, project.id)
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([token.model_dump() for token in tokens])
        return

    if not tokens:
        app_context.output.info(f"No runtime tokens found for project {project.name}.")
        return

    rows = [
        [
            token.name,
            token.environment_name or "-",
            token.expires_at or "-",
            token.created_at or "-",
            token.last_used_at or "-",
            "yes" if token.active else "no",
        ]
        for token in tokens
    ]
    app_context.output.table(
        "Runtime Tokens",
        ["Name", "Environment", "Expires", "Created", "Last Used", "Active"],
        rows,
    )


@app.command("create")
def create_token(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Token name.")],
    environment_name: Annotated[str | None, typer.Option("--env", help="Environment name or ID.")] = None,
    expires: Annotated[str | None, typer.Option("--expires", help="Token lifetime, for example 30d or never.")] = None,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = _resolve_token_environment(app_context, client, project.id, project.name, environment_name)
        request = CreateRuntimeTokenRequest(name=name, environment_id=environment.id, expires_in=expires)
        response = client.request_model(
            "POST",
            build_path(
                Endpoint.CREATE_RUNTIME_TOKEN,
                project_id=project.id,
                environment_id=environment.id,
            ),
            CreateRuntimeTokenResponse,
            json_body=request.model_dump(exclude_none=True),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(response.model_dump())
        return

    app_context.output.success(f"Created token {response.metadata.name}")
    app_context.output.info("Copy this token now. It may not be shown again.")
    app_context.output.write(response.token)


@app.command("reveal")
def reveal_token(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Token name.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        response = client.request_model(
            "POST",
            build_path(Endpoint.REVEAL_RUNTIME_TOKEN_BY_NAME, project_id=project.id),
            PlaintextTokenResponse,
            json_body=TokenByNameRequest(name=name).model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(response.model_dump())
        return

    app_context.output.info(f"Runtime token {name}:")
    app_context.output.write(response.token)


@app.command("revoke")
def revoke_token(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Token name.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        client.request(
            "POST",
            build_path(Endpoint.REVOKE_RUNTIME_TOKEN_BY_NAME, project_id=project.id),
            json_body=TokenByNameRequest(name=name).model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json({"revoked": True, "name": name})
        return

    app_context.output.success(f"Revoked token {name}")


@app.command("share")
def share_token(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Token name.")],
    email: Annotated[str, typer.Option("--email", help="Recipient email.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        token = _resolve_runtime_token(client, project.id, name)
        client.request(
            "POST",
            build_path(Endpoint.TOKEN_SHARE, token_id=token.id),
            json_body=ShareTokenRequest(email=email).model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json({"shared": True, "name": name, "email": email})
        return

    app_context.output.success(f"Shared token {name} with {email}")


@app.command("shares")
def list_token_shares(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Token name.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        token = _resolve_runtime_token(client, project.id, name)
        shares = client.request_model(
            "GET",
            build_path(Endpoint.TOKEN_SHARES, token_id=token.id),
            list[TokenShareSummary],
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([share.model_dump() for share in shares])
        return

    if not shares:
        app_context.output.info(f"No shares found for token {name}.")
        return

    rows = [[share.email, share.shared_at or "-", share.shared_by or "-"] for share in shares]
    app_context.output.table("Token Shares", ["Email", "Shared At", "Shared By"], rows)


def _list_runtime_tokens(client: EnvBasisClient, project_id: str) -> list[RuntimeTokenSummary]:
    return client.request_model(
        "GET",
        build_path(Endpoint.RUNTIME_TOKENS, project_id=project_id),
        list[RuntimeTokenSummary],
    )


def _resolve_runtime_token(client: EnvBasisClient, project_id: str, name: str) -> RuntimeTokenSummary:
    tokens = _list_runtime_tokens(client, project_id)
    matches = [token for token in tokens if token.name == name]
    if not matches:
        raise APIError(404, f'Token "{name}" not found.')
    if len(matches) > 1:
        raise APIError(409, f'Token name "{name}" is ambiguous. Use a token ID instead.')
    return matches[0]


def _resolve_token_environment(
    app_context: AppContext,
    client: EnvBasisClient,
    project_id: str,
    project_name: str,
    environment_reference: str | None,
):
    environments = fetch_environments(client, project_id)
    if environment_reference:
        return _match_environment(app_context, environments, project_name, environment_reference)

    if not environments:
        app_context.output.error(
            f"Project {project_name} has no environments. Run envbasis env create <name>."
        )
        raise typer.Exit(code=1)

    if len(environments) == 1:
        return environments[0]

    app_context.output.info(f"Select an environment for project {project_name}:")
    for index, environment in enumerate(environments, start=1):
        app_context.output.info(f"{index}. {environment.name}")

    selection = typer.prompt("Environment")
    return _match_environment(app_context, environments, project_name, selection.strip())


def _match_environment(
    app_context: AppContext,
    environments,
    project_name: str,
    selection: str,
):
    if selection.isdigit():
        selected_index = int(selection) - 1
        if 0 <= selected_index < len(environments):
            return environments[selected_index]

    for environment in environments:
        if environment.id == selection or environment.name == selection:
            return environment

    app_context.output.error(f'Environment "{selection}" not found in project {project_name}.')
    raise typer.Exit(code=1)
