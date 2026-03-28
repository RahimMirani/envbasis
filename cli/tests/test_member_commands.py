from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "member-auth-token"

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


def test_members_list_renders_table(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/members",
                "status_code": 200,
                "payload": [
                    {
                        "email": "dev@example.com",
                        "role": "owner",
                        "secret_access": True,
                        "joined_at": "2026-03-15T10:00:00Z",
                    }
                ],
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["members", "list"])

    assert result.exit_code == 0
    assert "dev@example.com" in result.output
    assert "owner" in result.output


def test_invite_member_succeeds(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/invite",
                "json": {"email": "new@example.com"},
                "status_code": 204,
                "payload": None,
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["invite", "new@example.com"])

    assert result.exit_code == 0
    assert "Invited new@example.com" in result.output


def test_member_access_allow_posts_correct_payload(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/members/access",
                "json": {"email": "dev@example.com", "can_push_pull_secrets": True},
                "status_code": 204,
                "payload": None,
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["members", "access", "dev@example.com", "--allow"])

    assert result.exit_code == 0
    assert "Granted secret access for dev@example.com" in result.output


def test_member_access_requires_exactly_one_flag(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--api-url", "https://api.example.com/api/v1", "members", "access", "dev@example.com"],
    )

    assert result.exit_code == 1
    assert "Pass exactly one of --allow or --deny." in result.output


def test_revoke_member_conflict_prompts_and_retries(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/revoke",
                "json": {"email": "dev@example.com"},
                "status_code": 409,
                "payload": {"detail": "Member owns shared runtime tokens."},
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/revoke",
                "json": {"email": "dev@example.com", "keep_shared_tokens": True},
                "status_code": 204,
                "payload": None,
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["revoke", "dev@example.com"], input="1\n")

    assert result.exit_code == 0
    assert "Member owns shared runtime tokens." in result.output
    assert "1. Keep shared tokens" in result.output
    assert "2. Revoke shared tokens" in result.output
    assert "Revoked dev@example.com" in result.output


def test_revoke_member_conflict_invalid_selection_aborts(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/revoke",
                "json": {"email": "dev@example.com"},
                "status_code": 409,
                "payload": {"detail": "Member owns shared runtime tokens."},
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["revoke", "dev@example.com"], input="3\n")

    assert result.exit_code == 1
    assert "Aborted." in result.output


def test_revoke_member_with_flag_emits_json(monkeypatch, tmp_path) -> None:
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
                "auth": "member-auth-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/revoke",
                "json": {"email": "dev@example.com", "keep_shared_tokens": True},
                "status_code": 204,
                "payload": None,
                "auth": "member-auth-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "revoke", "dev@example.com", "--keep-shared-tokens"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"revoked": True, "email": "dev@example.com"}
