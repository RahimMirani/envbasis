from __future__ import annotations

import json

import click
import httpx
import pytest
from typer.testing import CliRunner

from envbasis_cli.command_support import build_client, resolve_environment
from envbasis_cli.config import ConfigManager
from envbasis_cli.context import AppContext, GlobalOptions
from envbasis_cli.main import app
from envbasis_cli.output import OutputManager
from envbasis_cli.contracts import ProjectSummary


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "env-token"

    def get(self) -> str | None:
        return self.token

    def set(self, token: str) -> None:
        self.token = token

    def delete(self) -> None:
        self.token = None


def _wire_main_dependencies(monkeypatch, tmp_path, token_store: FakeTokenStore) -> None:
    config_path = tmp_path / ".envbasis.toml"
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", lambda: token_store)


def _mock_http(monkeypatch, responses: list[dict[str, object]]) -> None:
    pending = responses.copy()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        assert pending, f"Unexpected request: {method} {url}"
        expected = pending.pop(0)
        assert method == expected["method"]
        assert url == expected["url"]

        expected_json = expected.get("json")
        if expected_json is None:
            assert json is None
        else:
            assert json == expected_json

        expected_auth = expected.get("auth")
        if expected_auth is None:
            assert headers is None or "Authorization" not in headers
        else:
            assert headers is not None
            assert headers["Authorization"] == f"Bearer {expected_auth}"

        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(int(expected["status_code"]), json=expected["payload"], request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def test_env_list_uses_selected_project(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\n',
        encoding="utf-8",
    )
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [{"id": "proj_1", "name": "my-ai-app"}],
                "auth": "env-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "env-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["env", "list"])

    assert result.exit_code == 0
    assert "dev" in result.output
    assert "prod" in result.output


def test_env_create_emits_json(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\n',
        encoding="utf-8",
    )
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [{"id": "proj_1", "name": "my-ai-app"}],
                "auth": "env-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "json": {"name": "dev"},
                "status_code": 200,
                "payload": {"id": "env_1", "name": "dev"},
                "auth": "env-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "env", "create", "dev"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"id": "env_1", "name": "dev", "created_at": None, "updated_at": None}


def test_env_list_requires_selected_project(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "env", "list"])

    assert result.exit_code == 1
    assert "No project selected." in result.output


def test_env_use_persists_selection(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\n',
        encoding="utf-8",
    )
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [{"id": "proj_1", "name": "my-ai-app"}],
                "auth": "env-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "env-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["env", "use", "prod"])

    assert result.exit_code == 0
    config_text = config_path.read_text(encoding="utf-8")
    assert 'environment = "prod"' in config_text
    assert "Selected environment prod" in result.output


def test_resolve_environment_auto_selects_single_environment(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\n',
        encoding="utf-8",
    )
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "env-token",
            }
        ],
    )

    app_context = AppContext(
        options=GlobalOptions(
            api_url=None,
            env_api_url=None,
            project=None,
            environment=None,
            output_json=False,
            verbose=False,
        ),
        config_manager=ConfigManager(config_path),
        local_config=ConfigManager(config_path).load(),
        auth_manager=token_store,
        output=OutputManager(),
    )
    client = build_client(app_context)
    project = ProjectSummary(id="proj_1", name="my-ai-app")

    environment = resolve_environment(app_context, client, project)

    assert environment.id == "env_1"
    assert environment.name == "dev"


def test_resolve_environment_fails_when_multiple_exist_without_selection(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\n',
        encoding="utf-8",
    )
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "env-token",
            }
        ],
    )

    app_context = AppContext(
        options=GlobalOptions(
            api_url=None,
            env_api_url=None,
            project=None,
            environment=None,
            output_json=False,
            verbose=False,
        ),
        config_manager=ConfigManager(config_path),
        local_config=ConfigManager(config_path).load(),
        auth_manager=token_store,
        output=OutputManager(),
    )
    client = build_client(app_context)
    project = ProjectSummary(id="proj_1", name="my-ai-app")

    with pytest.raises(click.exceptions.Exit) as exc_info:
        resolve_environment(app_context, client, project)

    assert exc_info.value.exit_code == 1


def test_resolve_environment_prefers_explicit_flag_over_saved_env(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\nenvironment = "dev"\n',
        encoding="utf-8",
    )
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "env-token",
            }
        ],
    )

    app_context = AppContext(
        options=GlobalOptions(
            api_url=None,
            env_api_url=None,
            project=None,
            environment="prod",
            output_json=False,
            verbose=False,
        ),
        config_manager=ConfigManager(config_path),
        local_config=ConfigManager(config_path).load(),
        auth_manager=token_store,
        output=OutputManager(),
    )
    client = build_client(app_context)
    project = ProjectSummary(id="proj_1", name="my-ai-app")

    environment = resolve_environment(app_context, client, project)

    assert environment.id == "env_2"
    assert environment.name == "prod"
