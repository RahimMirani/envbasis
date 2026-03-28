from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer

from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.client import APIError
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import (
    CreateSecretRequest,
    Endpoint,
    PullSecretsResponse,
    PushSecretsRequest,
    PushSecretsResponse,
    SecretMetadata,
    SecretsListResponse,
    SecretsStats,
    UpdateSecretRequest,
    build_path,
)
from envbasis_cli.secret_files import (
    SecretReview,
    build_secret_review,
    git_safety_warnings,
    load_dotenv_file,
    render_secret_payload,
    write_secret_file,
)

app = typer.Typer(help="Push, pull, and manage secrets.")


def register(root_app: typer.Typer) -> None:
    @root_app.command("push")
    def push_secrets(
        ctx: typer.Context,
        file: Annotated[Path, typer.Option("--file", help="Path to dotenv file.")] = Path(".env"),
        review: Annotated[
            bool,
            typer.Option(
                "--review",
                help="Preview a masked diff against the current remote secrets and confirm before pushing.",
            ),
        ] = False,
        yes: Annotated[
            bool,
            typer.Option("--yes", help="Skip the review confirmation prompt. Requires --review."),
        ] = False,
    ) -> None:
        app_context = require_app_context(ctx)

        if yes and not review:
            app_context.output.error(
                "--yes can only be used with --review. Did you mean: envbasis push --review --yes?"
            )
            raise typer.Exit(code=1)

        if review and app_context.options.output_json:
            app_context.output.error("Review mode is not supported with --json.")
            raise typer.Exit(code=1)

        client = build_client(app_context)
        file_path = file.expanduser().resolve()

        for warning in git_safety_warnings(file_path):
            app_context.output.info(f"Warning: {warning}")

        try:
            project = resolve_project(app_context, client)
            environment = resolve_environment(app_context, client, project)
            secrets = load_dotenv_file(file_path)
            if not secrets:
                app_context.output.error(f"No secrets found in {file_path}.")
                raise typer.Exit(code=1)
        except (FileNotFoundError, IsADirectoryError):
            app_context.output.error(f"Secret file not found: {file_path}")
            raise typer.Exit(code=1)
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        if review:
            try:
                remote_secrets = client.request_model(
                    "GET",
                    build_path(
                        Endpoint.SECRETS_PULL,
                        project_id=project.id,
                        environment_id=environment.id,
                    ),
                    PullSecretsResponse,
                )
            except APIError as exc:
                raise exit_for_api_error(app_context, exc) from exc

            review_output = build_secret_review(remote_secrets.secrets, secrets)
            _emit_secret_review(app_context.output, review_output)

            if not review_output.has_changes:
                app_context.output.info("No changes to push.")
                return

            if not yes:
                confirmed = typer.confirm("Apply this push?", default=False)
                if not confirmed:
                    app_context.output.info("Aborted.")
                    raise typer.Exit(code=1)

        try:
            response = client.request_model(
                "POST",
                build_path(
                    Endpoint.SECRETS_PUSH,
                    project_id=project.id,
                    environment_id=environment.id,
                ),
                PushSecretsResponse,
                json_body=PushSecretsRequest(secrets=secrets).model_dump(),
            )
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        if app_context.options.output_json:
            app_context.output.emit_json(
                {
                    "file": str(file_path),
                    "project": project.name,
                    "environment": environment.name,
                    **response.model_dump(),
                }
            )
            return

        app_context.output.success(
            f"Pushed {response.changed} changed secrets, {response.unchanged} unchanged"
        )

    @root_app.command("pull")
    def pull_secrets(
        ctx: typer.Context,
        file: Annotated[Path, typer.Option("--file", help="Destination file path.")] = Path(".env"),
        stdout: Annotated[bool, typer.Option("--stdout", help="Write secrets to stdout instead of a file.")] = False,
        output_format: Annotated[
            Literal["dotenv", "json"],
            typer.Option("--format", help="Output format for pulled secrets."),
        ] = "dotenv",
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite", help="Overwrite existing files without confirmation."),
        ] = False,
    ) -> None:
        app_context = require_app_context(ctx)
        client = build_client(app_context)
        file_path = file.expanduser().resolve()

        try:
            project = resolve_project(app_context, client)
            environment = resolve_environment(app_context, client, project)
            response = client.request_model(
                "GET",
                build_path(
                    Endpoint.SECRETS_PULL,
                    project_id=project.id,
                    environment_id=environment.id,
                ),
                PullSecretsResponse,
            )
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        if stdout:
            if output_format == "json":
                app_context.output.emit_json(response.secrets)
            else:
                app_context.output.write(render_secret_payload(response.secrets, output_format), end="")
            return

        for warning in git_safety_warnings(file_path):
            app_context.output.info(f"Warning: {warning}")

        if file_path.exists() and not overwrite:
            overwrite = typer.confirm(f"{file_path} already exists. Overwrite it?")
            if not overwrite:
                app_context.output.info("Aborted.")
                raise typer.Exit(code=1)

        write_secret_file(file_path, response.secrets, output_format)

        if app_context.options.output_json:
            app_context.output.emit_json(
                {
                    "file": str(file_path),
                    "project": project.name,
                    "environment": environment.name,
                    "count": len(response.secrets),
                    "format": output_format,
                }
            )
            return

        app_context.output.success(f"Wrote {len(response.secrets)} secrets to {file_path}")


def _emit_secret_review(output, review: SecretReview) -> None:
    for line in review.lines:
        output.write_styled(line.text, style=line.style)


@app.command("list")
def list_secrets(
    ctx: typer.Context,
    reveal: Annotated[bool, typer.Option("--reveal", help="Show raw secret values if the backend returns them.")] = False,
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        secrets = client.request_model(
            "GET",
            build_path(
                Endpoint.SECRETS_LIST,
                project_id=project.id,
                environment_id=environment.id,
            ),
            SecretsListResponse,
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json([secret.model_dump() for secret in secrets.secrets])
        return

    if not secrets.secrets:
        app_context.output.info(f"No secrets found for environment {environment.name}.")
        return

    columns = ["Key", "Version", "Updated", "Updated By"]
    if reveal:
        columns.append("Value")

    rows = []
    for secret in secrets.secrets:
        row = [
            secret.key,
            str(secret.version or 0),
            secret.updated_at or "-",
            secret.updated_by or "-",
        ]
        if reveal:
            row.append(secret.value or "")
        rows.append(row)

    app_context.output.table("Secrets", columns, rows)


@app.command("stats")
def secrets_stats(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        stats = client.request_model(
            "GET",
            build_path(Endpoint.SECRETS_STATS, project_id=project.id),
            SecretsStats,
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(stats.model_dump())
        return

    app_context.output.info(f"Total secrets: {stats.total_secret_count}")
    if stats.generated_at:
        app_context.output.info(f"Generated at: {stats.generated_at}")
    if stats.environments:
        rows = [
            [
                environment.environment_name or environment.environment_id or "-",
                str(environment.secret_count),
                environment.last_updated_at or "-",
                environment.last_activity_at or "-",
            ]
            for environment in stats.environments
        ]
        app_context.output.table(
            "Secrets By Environment",
            ["Environment", "Count", "Last Updated", "Last Activity"],
            rows,
        )


@app.command("set")
def set_secret(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
    value: Annotated[str, typer.Argument(help="Secret value.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        request = CreateSecretRequest(key=key, value=value)
        response = client.request_model(
            "POST",
            build_path(
                Endpoint.SECRETS_LIST,
                project_id=project.id,
                environment_id=environment.id,
            ),
            SecretMetadata,
            json_body=request.model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(response.model_dump())
        return

    app_context.output.success(f"Set secret {key}")


@app.command("update")
def update_secret(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
    value: Annotated[str, typer.Argument(help="Updated secret value.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        request = UpdateSecretRequest(value=value)
        response = client.request_model(
            "PATCH",
            build_path(
                Endpoint.SECRET_DETAIL,
                project_id=project.id,
                environment_id=environment.id,
                key=key,
            ),
            SecretMetadata,
            json_body=request.model_dump(),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json(response.model_dump())
        return

    app_context.output.success(f"Updated secret {key}")


@app.command("delete")
def delete_secret(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Secret key.")],
) -> None:
    app_context = require_app_context(ctx)
    client = build_client(app_context)

    try:
        project = resolve_project(app_context, client)
        environment = resolve_environment(app_context, client, project)
        client.request(
            "DELETE",
            build_path(
                Endpoint.SECRET_DETAIL,
                project_id=project.id,
                environment_id=environment.id,
                key=key,
            ),
        )
    except APIError as exc:
        raise exit_for_api_error(app_context, exc) from exc

    if app_context.options.output_json:
        app_context.output.emit_json({"deleted": True, "key": key})
        return

    app_context.output.success(f"Deleted secret {key}")
