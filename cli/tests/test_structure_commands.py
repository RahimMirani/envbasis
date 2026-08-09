from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def get(self) -> str:
        return "secret-token"


def _wire(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nenvironment = "dev"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)


def _mock_http(monkeypatch, responses: list[dict[str, object]]) -> None:
    pending = responses.copy()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        expected = pending.pop(0)
        assert method == expected["method"]
        assert url == expected["url"]
        assert params == expected.get("params")
        assert json == expected.get("json")
        request = httpx.Request(method, url, headers=headers)
        if "payload" not in expected:
            return httpx.Response(int(expected["status_code"]), request=request)
        return httpx.Response(
            int(expected["status_code"]), json=expected["payload"], request=request
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def _context_requests() -> list[dict[str, object]]:
    return [
        {
            "method": "GET",
            "url": "https://api.example.com/api/v1/projects",
            "status_code": 200,
            "payload": [{"id": "proj_1", "name": "demo"}],
        },
        {
            "method": "GET",
            "url": "https://api.example.com/api/v1/projects/proj_1/environments",
            "status_code": 200,
            "payload": [{"id": "env_1", "name": "dev"}],
        },
    ]


def test_folder_create_and_recursive_list(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock_http(
        monkeypatch,
        _context_requests()
        + [
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/folders",
                "json": {"path": "/backend/payments", "description": "Payments"},
                "status_code": 201,
                "payload": {
                    "id": "folder_1",
                    "environment_id": "env_1",
                    "path": "/backend/payments",
                    "parent_path": "/backend",
                    "name": "payments",
                    "description": "Payments",
                },
            }
        ],
    )
    runner = CliRunner()
    created = runner.invoke(
        app, ["folders", "create", "/backend/payments", "--description", "Payments"]
    )
    assert created.exit_code == 0
    assert "Created folder /backend/payments" in created.output

    _mock_http(
        monkeypatch,
        _context_requests()
        + [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/folders",
                "params": {"path": "/backend", "recursive": True},
                "status_code": 200,
                "payload": {
                    "project_id": "proj_1",
                    "environment_id": "env_1",
                    "path": "/backend",
                    "recursive": True,
                    "folders": [],
                },
            }
        ],
    )
    listed = runner.invoke(
        app, ["--json", "folders", "list", "--path", "/backend", "--recursive"]
    )
    assert listed.exit_code == 0
    assert json.loads(listed.output)["recursive"] is True


def test_set_secret_sends_path_tags_and_metadata(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock_http(
        monkeypatch,
        _context_requests()
        + [
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets",
                "json": {
                    "key": "DATABASE_URL",
                    "value": "postgres://example",
                    "path": "/backend",
                    "tags": ["database"],
                    "description": "Primary database",
                    "owner": "platform@example.com",
                    "service": "api",
                    "rotation_interval_days": 30,
                    "custom_metadata": {"region": "us-west-2"},
                },
                "status_code": 201,
                "payload": {
                    "key": "DATABASE_URL",
                    "path": "/backend",
                    "tags": ["database"],
                    "version": 1,
                },
            }
        ],
    )
    result = CliRunner().invoke(
        app,
        [
            "secrets",
            "set",
            "DATABASE_URL",
            "postgres://example",
            "--path",
            "/backend",
            "--tag",
            "database",
            "--description",
            "Primary database",
            "--owner",
            "platform@example.com",
            "--service",
            "api",
            "--rotation-interval-days",
            "30",
            "--metadata",
            "region=us-west-2",
        ],
    )
    assert result.exit_code == 0
    assert "Set secret DATABASE_URL" in result.output


def test_recursive_pull_and_project_tag_creation(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock_http(
        monkeypatch,
        _context_requests()
        + [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "params": {
                    "path": "/backend",
                    "recursive": True,
                    "resolve": True,
                    "include_imports": True,
                    "tag": ["api"],
                },
                "status_code": 200,
                "payload": {"secrets": {"TOKEN": "value"}},
            }
        ],
    )
    pulled = CliRunner().invoke(
        app,
        ["secrets", "pull", "--stdout", "--path", "/backend", "--recursive", "--tag", "api"],
    )
    assert pulled.exit_code == 0
    assert "TOKEN=value" in pulled.output

    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [{"id": "proj_1", "name": "demo"}],
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/secret-tags",
                "json": {"name": "critical", "color": "#ff0000"},
                "status_code": 201,
                "payload": {
                    "id": "tag_1",
                    "project_id": "proj_1",
                    "name": "critical",
                    "color": "#ff0000",
                },
            },
        ],
    )
    tagged = CliRunner().invoke(app, ["tags", "create", "critical", "--color", "#ff0000"])
    assert tagged.exit_code == 0
    assert "Created tag critical" in tagged.output


def test_import_create_resolves_environment_names_and_serializes_rule(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    environments_response = {
        "method": "GET",
        "url": "https://api.example.com/api/v1/projects/proj_1/environments",
        "status_code": 200,
        "payload": [
            {"id": "env_dev", "name": "dev"},
            {"id": "env_shared", "name": "shared"},
        ],
    }
    _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects",
                "status_code": 200,
                "payload": [{"id": "proj_1", "name": "demo"}],
            },
            environments_response,
            environments_response,
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/secret-imports",
                "json": {
                    "source_environment_id": "env_shared",
                    "source_path": "/common",
                    "target_environment_id": "env_dev",
                    "target_path": "/backend",
                    "recursive": True,
                    "priority": 20,
                    "enabled": True,
                },
                "status_code": 201,
                "payload": {
                    "id": "import_1",
                    "project_id": "proj_1",
                    "source_environment_id": "env_shared",
                    "source_path": "/common",
                    "target_environment_id": "env_dev",
                    "target_path": "/backend",
                    "recursive": True,
                    "priority": 20,
                    "enabled": True,
                },
            },
        ],
    )
    result = CliRunner().invoke(
        app,
        [
            "imports",
            "create",
            "--from-env",
            "shared",
            "--from-path",
            "/common",
            "--to-path",
            "/backend",
            "--recursive",
            "--priority",
            "20",
        ],
    )
    assert result.exit_code == 0
    assert "Created import import_1" in result.output


def test_pull_can_return_unresolved_local_values_without_imports(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock_http(
        monkeypatch,
        _context_requests()
        + [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "params": {
                    "path": "/",
                    "recursive": False,
                    "resolve": False,
                    "include_imports": False,
                },
                "status_code": 200,
                "payload": {
                    "secrets": {"URL": "https://${HOST}"},
                    "resolution_mode": "unresolved",
                    "includes_imports": False,
                },
            }
        ],
    )
    result = CliRunner().invoke(app, ["secrets", "pull", "--stdout", "--no-resolve", "--no-imports"])
    assert result.exit_code == 0
    assert "URL=https://${HOST}" in result.output
