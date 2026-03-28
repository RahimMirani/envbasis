from __future__ import annotations

from typing import Any

import typer

from envbasis_cli.auth import AuthError
from envbasis_cli.client import APIError, EnvBasisClient
from envbasis_cli.config import API_URL_ENV_VAR
from envbasis_cli.context import AppContext
from envbasis_cli.contracts import Endpoint, EnvironmentSummary, ProjectSummary, build_path


def require_api_url(app_context: AppContext) -> str:
    api_url = app_context.resolved_api_url
    if api_url:
        return api_url

    app_context.output.error(
        f"API base URL is not set. Pass --api-url, set {API_URL_ENV_VAR}, or add api_base_url to .envbasis.toml."
    )
    raise typer.Exit(code=1)


def build_client(app_context: AppContext) -> EnvBasisClient:
    return EnvBasisClient(require_api_url(app_context), app_context.auth_manager)


def exit_for_api_error(app_context: AppContext, exc: APIError) -> typer.Exit:
    app_context.output.error(str(exc))
    return typer.Exit(code=1)


def fetch_projects(client: EnvBasisClient) -> list[ProjectSummary]:
    return client.request_model("GET", build_path(Endpoint.PROJECTS), list[ProjectSummary])


def resolve_project(
    app_context: AppContext,
    client: EnvBasisClient,
    *,
    reference: str | None = None,
) -> ProjectSummary:
    project_ref = reference or app_context.resolved_project
    if not project_ref:
        app_context.output.error(
            "No project selected. Pass --project or run envbasis project use <project-name-or-id>."
        )
        raise typer.Exit(code=1)

    projects = fetch_projects(client)
    matches = [project for project in projects if project.id == project_ref or project.name == project_ref]
    if not matches:
        app_context.output.error(f'Project "{project_ref}" not found.')
        raise typer.Exit(code=1)

    if len(matches) > 1:
        app_context.output.error(
            f'Project reference "{project_ref}" is ambiguous. Use a project ID instead.'
        )
        raise typer.Exit(code=1)

    return matches[0]


def persist_local_config(app_context: AppContext, **updates: Any) -> None:
    updated_config = app_context.local_config.model_copy(update=updates)
    app_context.config_manager.save(updated_config)
    app_context.local_config = updated_config


def fetch_environments(client: EnvBasisClient, project_id: str) -> list[EnvironmentSummary]:
    return client.request_model(
        "GET",
        build_path(Endpoint.ENVIRONMENTS, project_id=project_id),
        list[EnvironmentSummary],
    )


def resolve_environment(
    app_context: AppContext,
    client: EnvBasisClient,
    project: ProjectSummary,
    *,
    reference: str | None = None,
) -> EnvironmentSummary:
    environments = fetch_environments(client, project.id)
    environment_ref = reference or app_context.resolved_environment

    if environment_ref:
        matches = [
            environment
            for environment in environments
            if environment.id == environment_ref or environment.name == environment_ref
        ]
        if not matches:
            app_context.output.error(
                f'Environment "{environment_ref}" not found in project {project.name}.'
            )
            raise typer.Exit(code=1)

        if len(matches) > 1:
            app_context.output.error(
                f'Environment reference "{environment_ref}" is ambiguous. Use an environment ID instead.'
            )
            raise typer.Exit(code=1)

        return matches[0]

    if not environments:
        app_context.output.error(
            f'Project {project.name} has no environments. Run envbasis env create <name>.'
        )
        raise typer.Exit(code=1)

    if len(environments) == 1:
        return environments[0]

    app_context.output.error(
        f'Multiple environments exist for project {project.name}. Pass --env or run envbasis env use <name>.'
    )
    raise typer.Exit(code=1)
