from __future__ import annotations

from typing import Annotated, Literal

import typer

from envbasis_cli.client import APIError
from envbasis_cli.command_support import build_client, exit_for_api_error, resolve_environment, resolve_project
from envbasis_cli.context import require_app_context
from envbasis_cli.contracts import Endpoint, PullSecretsResponse, build_path
from envbasis_cli.execution import ProcessSupervisor, supervise_process


def register(root_app: typer.Typer) -> None:
    @root_app.command(
        "run",
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def run_command(
        ctx: typer.Context,
        watch: Annotated[
            bool,
            typer.Option("--watch", help="Restart the child when remote secrets change (development only)."),
        ] = False,
        watch_interval: Annotated[
            float,
            typer.Option("--watch-interval", min=0.1, help="Seconds between watch checks."),
        ] = 5.0,
        debounce: Annotated[
            float,
            typer.Option("--debounce", min=0.0, help="Seconds to debounce repeated secret changes."),
        ] = 0.5,
        precedence: Annotated[
            Literal["remote", "local"],
            typer.Option(
                "--precedence",
                help="Conflict policy: remote secrets override local variables by default.",
            ),
        ] = "remote",
        path: Annotated[
            str,
            typer.Option("--path", help="Secret path to fetch."),
        ] = "/",
        tag: Annotated[
            list[str] | None,
            typer.Option("--tag", help="Require a secret tag; repeat for multiple tags."),
        ] = None,
        recursive: Annotated[bool, typer.Option("--recursive", help="Include descendant folders.")] = False,
        resolve_references: Annotated[bool, typer.Option("--resolve/--no-resolve")] = True,
        include_imports: Annotated[bool, typer.Option("--imports/--no-imports")] = True,
    ) -> None:
        app_context = require_app_context(ctx)
        command = list(ctx.args)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            app_context.output.error("No child command provided. Use: envbasis run -- <command>")
            raise typer.Exit(code=2)

        client = build_client(app_context)
        try:
            project = resolve_project(app_context, client)
            environment = resolve_environment(app_context, client, project)
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        params: dict[str, object] = {
            "path": path,
            "recursive": recursive,
            "resolve": resolve_references,
            "include_imports": include_imports,
        }
        if tag:
            params["tag"] = tag

        def fetch_secrets() -> dict[str, str]:
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
                raise APIError(409, "; ".join(response.resolution_errors))
            return response.secrets

        def report_changes(keys: list[str]) -> None:
            if app_context.options.output_json:
                app_context.output.emit_json({"event": "secrets_changed", "keys": keys})
                return
            app_context.output.info("Secrets changed; restarting child: " + ", ".join(keys))

        try:
            secrets = fetch_secrets()
            supervisor = ProcessSupervisor(command, precedence=precedence)
            exit_code = supervise_process(
                supervisor,
                secrets,
                watch=watch,
                fetch_secrets=fetch_secrets if watch else None,
                poll_interval=watch_interval,
                debounce_seconds=debounce,
                report_changes=report_changes,
            )
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc
        except OSError as exc:
            app_context.output.error(f"Could not start child command: {exc}")
            raise typer.Exit(code=127) from exc

        raise typer.Exit(code=exit_code)
