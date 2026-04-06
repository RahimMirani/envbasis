from __future__ import annotations

from typing import Annotated

import typer

from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_project
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import (
    Endpoint,
    InviteMemberRequest,
    MemberAccessRequest,
    MemberSummary,
    RevokeMemberRequest,
    build_path,
)

app = typer.Typer(help="Manage project members and access.")


def register(root_app: typer.Typer) -> None:
    @root_app.command("invite")
    def invite_member(
        ctx: typer.Context,
        email: Annotated[str, typer.Argument(help="Member email.")],
    ) -> None:
        app_context = require_app_context(ctx)
        client = build_client(app_context)

        try:
            project = resolve_project(app_context, client)
            payload = client.request(
                "POST",
                build_path(Endpoint.INVITE, project_id=project.id),
                json_body=InviteMemberRequest(email=email).model_dump(),
            )
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        if app_context.options.output_json:
            app_context.output.emit_json(payload or {"invited": True, "email": email})
            return

        app_context.output.success(f"Invitation sent to {email}")

    @root_app.command("revoke")
    def revoke_member(
        ctx: typer.Context,
        email: Annotated[str, typer.Argument(help="Member email.")],
        keep_shared_tokens: Annotated[
            bool,
            typer.Option("--keep-shared-tokens", help="Keep shared runtime tokens after revoking the member."),
        ] = False,
        revoke_shared_tokens: Annotated[
            bool,
            typer.Option("--revoke-shared-tokens", help="Revoke shared runtime tokens when revoking the member."),
        ] = False,
    ) -> None:
        app_context = require_app_context(ctx)
        client = build_client(app_context)

        if keep_shared_tokens and revoke_shared_tokens:
            app_context.output.error(
                "Use either --keep-shared-tokens or --revoke-shared-tokens, not both."
            )
            raise typer.Exit(code=1)

        shared_action: str | None = None
        if keep_shared_tokens:
            shared_action = "keep_active"
        elif revoke_shared_tokens:
            shared_action = "revoke_tokens"

        request = RevokeMemberRequest(email=email, shared_token_action=shared_action)

        try:
            project = resolve_project(app_context, client)
            payload = _submit_revoke_request(client, project.id, request)
        except APIError as exc:
            if exc.status_code == 409 and not keep_shared_tokens and not revoke_shared_tokens:
                app_context.output.error(str(exc))
                app_context.output.info("Choose how to handle shared tokens:")
                app_context.output.info("1. Keep shared tokens")
                app_context.output.info("2. Revoke shared tokens")
                selection = typer.prompt("Selection").strip()

                if selection == "1":
                    request = RevokeMemberRequest(email=email, shared_token_action="keep_active")
                elif selection == "2":
                    request = RevokeMemberRequest(email=email, shared_token_action="revoke_tokens")
                else:
                    app_context.output.info("Aborted.")
                    raise typer.Exit(code=1) from exc

                try:
                    payload = _submit_revoke_request(client, project.id, request)
                except APIError as retry_exc:
                    raise exit_for_api_error(app_context, retry_exc) from retry_exc
            else:
                raise exit_for_api_error(app_context, exc) from exc

        if app_context.options.output_json:
            app_context.output.emit_json(payload or {"revoked": True, "email": email})
            return

        app_context.output.success(f"Revoked {email}")


def _submit_revoke_request(client, project_id: str, request: RevokeMemberRequest):
    return client.request(
        "POST",
        build_path(Endpoint.REVOKE_MEMBER, project_id=project_id),
        json_body=request.model_dump(exclude_none=True),
    )


@app.command("list")
def list_members(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        members = client.request_model(
            "GET",
            build_path(Endpoint.MEMBERS, project_id=project.id),
            list[MemberSummary],
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([member.model_dump() for member in members])
        return

    if not members:
        app_context.output.info(f"No members found for project {project.name}.")
        return

    rows = [
        [
            member.email,
            member.role or "-",
            "yes" if member.secret_access else "no",
            member.joined_at or "-",
        ]
        for member in members
    ]
    app_context.output.table("Members", ["Email", "Role", "Secret Access", "Joined"], rows)


@app.command("access")
def member_access(
    ctx: typer.Context,
    email: Annotated[str, typer.Argument(help="Member email.")],
    allow: Annotated[bool, typer.Option("--allow", help="Grant secret access.")] = False,
    deny: Annotated[bool, typer.Option("--deny", help="Deny secret access.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    if allow == deny:
        app_context.output.error("Pass exactly one of --allow or --deny.")
        raise typer.Exit(code=1)

    request = MemberAccessRequest(email=email, can_push_pull_secrets=allow)

    try:
        project = resolve_project(app_context, client)
        payload = client.request(
            "POST",
            build_path(Endpoint.MEMBER_ACCESS, project_id=project.id),
            json_body=request.model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(payload or {"email": email, "can_push_pull_secrets": allow})
        return

    verb = "Granted" if allow else "Denied"
    app_context.output.success(f"{verb} secret access for {email}")
