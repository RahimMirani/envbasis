from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer

from envbasis_cli.client import APIError
from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import Endpoint, PullSecretsResponse, build_path
from envbasis_cli.secret_files import render_secret_payload, write_secret_file


def register(root_app: typer.Typer) -> None:
    @root_app.command("export")
    def export_secrets(
        ctx: typer.Context,
        output_format: Annotated[
            Literal["dotenv", "json", "yaml", "shell"],
            typer.Option("--format", help="Secret export format."),
        ] = "dotenv",
        output_file: Annotated[
            Path | None,
            typer.Option("--output", "-o", help="Write to a file instead of stdout."),
        ] = None,
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite", help="Replace an existing output file without prompting."),
        ] = False,
        no_input: Annotated[
            bool,
            typer.Option("--no-input", help="Never prompt; fail if confirmation is required."),
        ] = False,
        path: Annotated[str, typer.Option("--path", help="Secret path to export.")] = "/",
        tag: Annotated[
            list[str] | None,
            typer.Option("--tag", help="Require a secret tag; repeat for multiple tags."),
        ] = None,
        recursive: Annotated[bool, typer.Option("--recursive", help="Include descendant folders.")] = False,
        resolve_references: Annotated[bool, typer.Option("--resolve/--no-resolve")] = True,
        include_imports: Annotated[bool, typer.Option("--imports/--no-imports")] = True,
    ) -> None:
        app_context = require_app_context(ctx)
        client = build_client(app_context)
        params: dict[str, object] = {
            "path": path,
            "recursive": recursive,
            "resolve": resolve_references,
            "include_imports": include_imports,
        }
        if tag:
            params["tag"] = tag

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
                params=params,
            )
            if resolve_references and response.resolution_errors:
                app_context.output.error("; ".join(response.resolution_errors))
                raise typer.Exit(code=1)
            rendered = render_secret_payload(response.secrets, output_format)
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc
        except ValueError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc

        if output_file is None:
            app_context.output.write(rendered, end="")
            return

        destination = output_file.expanduser().resolve()
        if destination.exists() and not overwrite:
            if no_input or app_context.options.output_json:
                app_context.output.error(
                    f"Output file already exists: {destination}. Pass --overwrite to replace it."
                )
                raise typer.Exit(code=1)
            if not typer.confirm(f"{destination} already exists. Overwrite it?", default=False):
                app_context.output.info("Aborted.")
                raise typer.Exit(code=1)

        write_secret_file(destination, response.secrets, output_format)
        payload = {
            "exported": True,
            "file": str(destination),
            "format": output_format,
            "count": len(response.secrets),
            "project": project.name,
            "environment": environment.name,
        }
        if app_context.options.output_json:
            app_context.output.emit_json(payload)
            return
        app_context.output.success(f"Exported {len(response.secrets)} secrets to {destination}")
