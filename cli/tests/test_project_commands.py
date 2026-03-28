from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "project-token"

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

        request = httpx.Request(method, url, headers=headers, json=json)
        return httpx.Response(int(expected["status_code"]), json=expected["payload"], request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def test_projects_list_renders_project_table(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [
                    {
                        "id": "proj_1",
                        "name": "my-ai-app",
                        "role": "owner",
                        "environment_count": 2,
                        "member_count": 4,
                        "token_count": 1,
                        "last_activity_at": "2026-03-15T10:00:00Z",
                    }
                ],
                "auth": "project-token",
            }
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "projects", "list"])

    assert result.exit_code == 0
    assert "my-ai-app" in result.output
    assert "owner" in result.output


def test_project_create_emits_json(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    _mock_http(
        monkeypatch,
        [
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects",
                "json": {"name": "my-ai-app", "description": "Hackathon app"},
                "status_code": 200,
                "payload": {
                    "id": "proj_1",
                    "name": "my-ai-app",
                    "description": "Hackathon app",
                    "role": "owner",
                    "environment_count": 0,
                    "member_count": 1,
                    "token_count": 0,
                },
                "auth": "project-token",
            }
        ],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "--api-url",
            "https://api.example.com/api/v1",
            "--json",
            "project",
            "create",
            "--name",
            "my-ai-app",
            "--description",
            "Hackathon app",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["name"] == "my-ai-app"


def test_project_use_persists_selection(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nenvironment = "stale-env"\n',
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
                "payload": [
                    {"id": "proj_1", "name": "my-ai-app"},
                    {"id": "proj_2", "name": "other-app"},
                ],
                "auth": "project-token",
            }
        ],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--api-url", "https://api.example.com/api/v1", "project", "use", "my-ai-app"],
    )

    assert result.exit_code == 0
    config_text = config_path.read_text(encoding="utf-8")
    assert 'project_id = "proj_1"' in config_text
    assert 'project_name = "my-ai-app"' in config_text
    assert 'environment = "stale-env"' not in config_text
    assert "Selected project my-ai-app" in result.output


def test_project_show_uses_saved_selection(monkeypatch, tmp_path) -> None:
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
                "payload": [{"id": "proj_1", "name": "my-ai-app", "role": "owner"}],
                "auth": "project-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1",
                "status_code": 200,
                "payload": {
                    "id": "proj_1",
                    "name": "my-ai-app",
                    "description": "Internal staging app",
                    "role": "owner",
                    "environment_count": 2,
                    "member_count": 4,
                    "token_count": 1,
                },
                "auth": "project-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["project", "show"])

    assert result.exit_code == 0
    assert "Internal staging app" in result.output
    assert "proj_1" in result.output


def test_project_update_refreshes_saved_name(monkeypatch, tmp_path) -> None:
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
                "auth": "project-token",
            },
            {
                "method": "PATCH",
                "url": "https://api.example.com/api/v1/projects/proj_1",
                "json": {"name": "renamed-app"},
                "status_code": 200,
                "payload": {
                    "id": "proj_1",
                    "name": "renamed-app",
                    "description": "Hackathon app",
                    "role": "owner",
                },
                "auth": "project-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["project", "update", "--name", "renamed-app"])

    assert result.exit_code == 0
    config_text = config_path.read_text(encoding="utf-8")
    assert 'project_name = "renamed-app"' in config_text
    assert "Updated project renamed-app" in result.output


def test_project_show_requires_selection(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "project", "show"])

    assert result.exit_code == 1
    assert "No project selected." in result.output
