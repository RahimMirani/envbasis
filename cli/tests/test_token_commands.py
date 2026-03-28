from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "runtime-token-auth"

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
        payload = expected.get("payload")
        if payload is None:
            return httpx.Response(int(expected["status_code"]), request=request)
        return httpx.Response(int(expected["status_code"]), json=payload, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def test_token_list_renders_table(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens",
                "status_code": 200,
                "payload": [
                    {
                        "id": "tok_1",
                        "name": "cli-prod-api",
                        "environment_name": "prod",
                        "expires_at": "2026-06-01T00:00:00Z",
                        "active": True,
                    }
                ],
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "list"])

    assert result.exit_code == 0
    assert "cli-prod-api" in result.output
    assert "prod" in result.output


def test_token_create_emits_json(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "prod"}],
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/runtime-tokens",
                "json": {
                    "name": "cli-prod-api",
                    "environment_id": "env_1",
                    "expires_in": "90d",
                },
                "status_code": 200,
                "payload": {
                    "token": "rt_live_token",
                    "metadata": {
                        "id": "tok_1",
                        "name": "cli-prod-api",
                        "environment_id": "env_1",
                        "environment_name": "prod",
                        "active": True,
                    },
                },
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--json", "token", "create", "--name", "cli-prod-api", "--env", "prod", "--expires", "90d"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["token"] == "rt_live_token"


def test_token_create_auto_selects_only_environment(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "prod"}],
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/runtime-tokens",
                "json": {
                    "name": "cli-prod-api",
                    "environment_id": "env_1",
                },
                "status_code": 200,
                "payload": {
                    "token": "rt_live_token",
                    "metadata": {
                        "id": "tok_1",
                        "name": "cli-prod-api",
                        "environment_id": "env_1",
                        "environment_name": "prod",
                        "active": True,
                    },
                },
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "create", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert "Created token cli-prod-api" in result.output
    assert "rt_live_token" in result.output


def test_token_create_accepts_flat_backend_payload(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "prod"}],
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/runtime-tokens",
                "json": {
                    "name": "cli-prod-api",
                    "environment_id": "env_1",
                },
                "status_code": 200,
                "payload": {
                    "id": "tok_1",
                    "name": "cli-prod-api",
                    "environment_id": "env_1",
                    "environment_name": "prod",
                    "active": True,
                    "plain_text_token": "rt_flat_live_token",
                },
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "create", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert "Created token cli-prod-api" in result.output
    assert "rt_flat_live_token" in result.output


def test_token_create_prompts_for_environment_when_multiple_exist(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_2/runtime-tokens",
                "json": {
                    "name": "cli-prod-api",
                    "environment_id": "env_2",
                },
                "status_code": 200,
                "payload": {
                    "token": "rt_selected_token",
                    "metadata": {
                        "id": "tok_1",
                        "name": "cli-prod-api",
                        "environment_id": "env_2",
                        "environment_name": "prod",
                        "active": True,
                    },
                },
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "create", "--name", "cli-prod-api"], input="2\n")

    assert result.exit_code == 0
    assert "Select an environment for project my-ai-app:" in result.output
    assert "1. dev" in result.output
    assert "2. prod" in result.output
    assert "rt_selected_token" in result.output


def test_token_reveal_prints_plaintext_token(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens/reveal-by-name",
                "json": {"name": "cli-prod-api"},
                "status_code": 200,
                "payload": {"token": "rt_revealed_token"},
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "reveal", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert "rt_revealed_token" in result.output


def test_token_reveal_accepts_flat_backend_payload(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens/reveal-by-name",
                "json": {"name": "cli-prod-api"},
                "status_code": 200,
                "payload": {
                    "token_id": "tok_1",
                    "name": "cli-prod-api",
                    "plain_text_token": "rt_revealed_flat_token",
                },
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "reveal", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert "rt_revealed_flat_token" in result.output


def test_token_revoke_succeeds(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens/revoke-by-name",
                "json": {"name": "cli-prod-api"},
                "status_code": 204,
                "payload": None,
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["token", "revoke", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert "Revoked token cli-prod-api" in result.output


def test_token_share_uses_name_resolution(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens",
                "status_code": 200,
                "payload": [{"id": "tok_1", "name": "cli-prod-api", "active": True}],
                "auth": "runtime-token-auth",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/runtime-tokens/tok_1/share",
                "json": {"email": "member@example.com"},
                "status_code": 204,
                "payload": None,
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["token", "share", "--name", "cli-prod-api", "--email", "member@example.com"],
    )

    assert result.exit_code == 0
    assert "Shared token cli-prod-api with member@example.com" in result.output


def test_token_shares_emits_json(monkeypatch, tmp_path) -> None:
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
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/runtime-tokens",
                "status_code": 200,
                "payload": [{"id": "tok_1", "name": "cli-prod-api", "active": True}],
                "auth": "runtime-token-auth",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/runtime-tokens/tok_1/shares",
                "status_code": 200,
                "payload": [
                    {
                        "email": "member@example.com",
                        "shared_at": "2026-03-15T10:00:00Z",
                        "shared_by": "owner@example.com",
                    }
                ],
                "auth": "runtime-token-auth",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "token", "shares", "--name", "cli-prod-api"])

    assert result.exit_code == 0
    assert json.loads(result.output)[0]["email"] == "member@example.com"
