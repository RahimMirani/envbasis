from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "audit-auth-token"

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


def test_audit_logs_renders_table(monkeypatch, tmp_path) -> None:
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
                "auth": "audit-auth-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/audit-logs",
                "status_code": 200,
                "payload": [
                    {
                        "id": "log_1",
                        "actor": "owner@example.com",
                        "action": "secret.push",
                        "environment": "prod",
                        "created_at": "2026-03-15T10:00:00Z",
                    }
                ],
                "auth": "audit-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["audit", "logs"])

    assert result.exit_code == 0
    assert "owner@example.com" in result.output
    assert "secret.push" in result.output


def test_audit_logs_emit_json(monkeypatch, tmp_path) -> None:
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
                "auth": "audit-auth-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/audit-logs",
                "status_code": 200,
                "payload": [
                    {
                        "id": "log_1",
                        "actor": "owner@example.com",
                        "action": "secret.push",
                        "environment": "prod",
                        "created_at": "2026-03-15T10:00:00Z",
                    }
                ],
                "auth": "audit-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "audit", "logs"])

    assert result.exit_code == 0
    assert json.loads(result.output)[0]["action"] == "secret.push"
