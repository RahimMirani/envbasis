from __future__ import annotations

import json

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager, normalize_api_base_url
from envbasis_cli.main import app


class FakeTokenStore:
    def get(self) -> str:
        return "init-token"


def _wire_main_dependencies(monkeypatch, tmp_path) -> ConfigManager:
    config_manager = ConfigManager(tmp_path / ".envbasis.toml")
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: config_manager)
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)
    return config_manager


def _mock_http(monkeypatch, responses: list[dict[str, object]]) -> list[dict[str, object]]:
    pending = responses.copy()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        assert pending, f"Unexpected request: {method} {url}"
        expected = pending.pop(0)
        assert method == expected["method"]
        assert url == expected["url"]
        assert headers is not None
        assert headers["Authorization"] == "Bearer init-token"
        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(
            int(expected["status_code"]),
            json=expected["payload"],
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return pending


def _successful_responses(api_url: str) -> list[dict[str, object]]:
    return [
        {
            "method": "GET",
            "url": f"{api_url}/auth/me",
            "status_code": 200,
            "payload": {"id": "user_1", "email": "dev@example.com"},
        },
        {
            "method": "GET",
            "url": f"{api_url}/projects",
            "status_code": 200,
            "payload": [
                {"id": "proj_1", "name": "payments"},
                {"id": "proj_2", "name": "agent-api"},
            ],
        },
        {
            "method": "GET",
            "url": f"{api_url}/projects/proj_2/environments",
            "status_code": 200,
            "payload": [
                {"id": "env_1", "name": "dev"},
                {"id": "env_2", "name": "prod"},
            ],
        },
    ]


def test_init_interactively_selects_and_saves_validated_configuration(monkeypatch, tmp_path) -> None:
    config_manager = _wire_main_dependencies(monkeypatch, tmp_path)
    api_url = "https://api.example.com/api/v1"
    pending = _mock_http(monkeypatch, _successful_responses(api_url))
    runner = CliRunner()

    result = runner.invoke(app, ["init"], input=f"{api_url}\n2\n2\n")

    assert result.exit_code == 0
    assert not pending
    assert "Initialized EnvBasis for agent-api/prod" in result.output
    saved = config_manager.load()
    assert saved.api_base_url == api_url
    assert saved.project_id == "proj_2"
    assert saved.project_name == "agent-api"
    assert saved.environment == "prod"


def test_init_supports_noninteractive_flags_and_json(monkeypatch, tmp_path) -> None:
    config_manager = _wire_main_dependencies(monkeypatch, tmp_path)
    api_url = "https://api.example.com/api/v1"
    pending = _mock_http(monkeypatch, _successful_responses(api_url))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "--json",
            "init",
            "--api-url",
            f"{api_url}/",
            "--project",
            "agent-api",
            "--env",
            "env_2",
        ],
    )

    assert result.exit_code == 0
    assert not pending
    payload = json.loads(result.output)
    assert payload["configured"] is True
    assert payload["api_url"] == api_url
    assert payload["project_id"] == "proj_2"
    assert payload["environment"] == "prod"
    assert config_manager.load().environment == "prod"


def test_init_rejects_invalid_api_url_without_overwriting_config(monkeypatch, tmp_path) -> None:
    config_manager = _wire_main_dependencies(monkeypatch, tmp_path)
    original = 'api_base_url = "https://old.example.com/api/v1"\nproject_name = "old"\n'
    config_manager.path.write_text(original, encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--api-url", "api.example.com/api/v1"])

    assert result.exit_code == 1
    assert "complete http:// or https:// URL" in result.output
    assert config_manager.path.read_text(encoding="utf-8") == original


def test_init_does_not_save_when_server_validation_fails(monkeypatch, tmp_path) -> None:
    config_manager = _wire_main_dependencies(monkeypatch, tmp_path)
    original = 'api_base_url = "https://old.example.com/api/v1"\n'
    config_manager.path.write_text(original, encoding="utf-8")
    api_url = "https://api.example.com/api/v1"
    pending = _mock_http(
        monkeypatch,
        [
            {
                "method": "GET",
                "url": f"{api_url}/auth/me",
                "status_code": 401,
                "payload": {"detail": "You are not logged in."},
            }
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--api-url", api_url])

    assert result.exit_code == 1
    assert not pending
    assert "You are not logged in" in result.output
    assert config_manager.path.read_text(encoding="utf-8") == original


def test_init_requires_flags_when_json_mode_has_multiple_choices(monkeypatch, tmp_path) -> None:
    config_manager = _wire_main_dependencies(monkeypatch, tmp_path)
    api_url = "https://api.example.com/api/v1"
    pending = _mock_http(monkeypatch, _successful_responses(api_url)[:2])
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "init", "--api-url", api_url])

    assert result.exit_code == 1
    assert not pending
    assert "Multiple projects are available. Select one with --project." in result.output
    assert not config_manager.path.exists()


def test_normalize_api_base_url_rejects_embedded_credentials() -> None:
    try:
        normalize_api_base_url("https://user:password@api.example.com/api/v1")
    except ValueError as exc:
        assert "username or password" in str(exc)
    else:
        raise AssertionError("Expected an API URL containing credentials to be rejected")
