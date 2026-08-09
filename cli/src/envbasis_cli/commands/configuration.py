from __future__ import annotations

import typer

from envbasis_cli.client import APIError, EnvBasisClient
from envbasis_cli.command_support import fetch_environments, fetch_projects
from envbasis_cli.config import CURRENT_CONFIG_VERSION, ConfigError, normalize_api_base_url
from envbasis_cli.context import AppContext, require_app_context
from envbasis_cli.contracts import Endpoint, UserProfile, build_path


app = typer.Typer(help="Inspect, validate, and migrate local CLI configuration.")


@app.command("check")
def check_configuration(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    checks: list[dict[str, object]] = []

    _add_check(
        checks,
        "configuration_file",
        app_context.config_manager.path.exists(),
        str(app_context.config_manager.path),
        "Run envbasis init in this repository." if not app_context.config_manager.path.exists() else None,
    )

    if app_context.config_error:
        _add_check(checks, "configuration_syntax", False, "invalid", app_context.config_error)
        _finish_check(app_context, checks)
        return

    _add_check(checks, "configuration_syntax", True, "valid")
    version = app_context.local_config.config_version
    _add_check(
        checks,
        "configuration_version",
        version == CURRENT_CONFIG_VERSION,
        f"{version} (current: {CURRENT_CONFIG_VERSION})",
        "Run envbasis config migrate." if version < CURRENT_CONFIG_VERSION else None,
    )

    try:
        api_url = normalize_api_base_url(app_context.resolved_api_url)
    except ValueError as exc:
        _add_check(checks, "api_url", False, str(app_context.resolved_api_url), str(exc))
        _finish_check(app_context, checks)
        return

    _add_check(checks, "api_url", True, api_url)
    client = EnvBasisClient(api_url, app_context.auth_manager)

    try:
        user = client.request_model("GET", build_path(Endpoint.AUTH_ME), UserProfile)
        _add_check(checks, "authentication", True, user.email)

        projects = fetch_projects(client)
        project, project_error = _find_selection(projects, app_context.resolved_project, "project")
        if project is None:
            _add_check(checks, "project", False, str(app_context.resolved_project or "not selected"), project_error)
            _finish_check(app_context, checks)
            return
        _add_check(checks, "project", True, f"{project.name} ({project.id})")

        environments = fetch_environments(client, project.id)
        environment, environment_error = _find_selection(
            environments,
            app_context.resolved_environment,
            "environment",
        )
        if environment is None:
            _add_check(
                checks,
                "environment",
                False,
                str(app_context.resolved_environment or "not selected"),
                environment_error,
            )
            _finish_check(app_context, checks)
            return
        _add_check(checks, "environment", True, f"{environment.name} ({environment.id})")
    except APIError as exc:
        _add_check(checks, "api_connection", False, "failed", str(exc))

    _finish_check(app_context, checks)


@app.command("migrate")
def migrate_configuration(ctx: typer.Context) -> None:
    app_context = require_app_context(ctx)
    try:
        result = app_context.config_manager.migrate()
        app_context.local_config = app_context.config_manager.load()
        app_context.config_error = None
    except ConfigError as exc:
        app_context.output.error(str(exc))
        raise typer.Exit(code=1) from exc

    payload = {
        "migrated": result.migrated,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "config_path": str(result.config_path),
        "backup_path": str(result.backup_path) if result.backup_path else None,
    }
    if app_context.options.output_json:
        app_context.output.emit_json(payload)
        return

    if not result.migrated:
        app_context.output.success(
            f"Configuration is already at version {result.new_version}; no migration was needed."
        )
        return

    app_context.output.success(
        f"Migrated configuration from version {result.old_version} to {result.new_version}."
    )
    app_context.output.info(f"Backup saved to {result.backup_path}")


def _find_selection(items, reference: str | None, label: str):
    if not reference:
        return None, f"No {label} is selected. Run envbasis init."
    matches = [item for item in items if item.id == reference or item.name == reference]
    if not matches:
        return None, f'The selected {label} "{reference}" no longer exists or is inaccessible.'
    if len(matches) > 1:
        return None, f'The selected {label} "{reference}" is ambiguous; select it by ID.'
    return matches[0], None


def _add_check(
    checks: list[dict[str, object]],
    name: str,
    ok: bool,
    value: str,
    guidance: str | None = None,
) -> None:
    checks.append({"name": name, "ok": ok, "value": value, "guidance": guidance})


def _finish_check(app_context: AppContext, checks: list[dict[str, object]]) -> None:
    valid = all(bool(check["ok"]) for check in checks)
    payload = {
        "valid": valid,
        "config_path": str(app_context.config_manager.path),
        "checks": checks,
    }

    if app_context.options.output_json:
        app_context.output.emit_json(payload)
    else:
        rows = [
            [
                "OK" if bool(check["ok"]) else "FAIL",
                str(check["name"]),
                str(check["value"]),
                str(check["guidance"] or "-"),
            ]
            for check in checks
        ]
        app_context.output.table(
            "EnvBasis Configuration Check",
            ["Status", "Check", "Value", "Guidance"],
            rows,
        )

    if not valid:
        raise typer.Exit(code=1)
