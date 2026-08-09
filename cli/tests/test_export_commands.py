from __future__ import annotations

import json
import os

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app
from envbasis_cli.secret_files import render_secret_payload


class FakeTokenStore:
    def get(self) -> str:
        return "export-token"


def _wire(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'config_version = 1\napi_base_url = "https://api.example.com/api/v1"\n'
        'project_id = "proj_1"\nproject_name = "agent-api"\nenvironment = "dev"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)


def _mock_export(monkeypatch, *, secrets: dict[str, str]) -> list[tuple[str, str]]:
    pending = [
        ("GET", "https://api.example.com/api/v1/projects"),
        ("GET", "https://api.example.com/api/v1/projects/proj_1/environments"),
        ("GET", "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull"),
    ]

    def fake_request(self, method, url, params=None, json=None, headers=None):
        assert pending.pop(0) == (method, url)
        request = httpx.Request(method, url, headers=headers)
        if url.endswith("/projects"):
            payload = [{"id": "proj_1", "name": "agent-api"}]
        elif url.endswith("/environments"):
            payload = [{"id": "env_1", "name": "dev"}]
        else:
            assert params == {
                "path": "/backend",
                "recursive": False,
                "resolve": True,
                "include_imports": True,
                "tag": ["api", "shared"],
            }
            payload = {"secrets": secrets}
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return pending


def test_export_stdout_has_no_status_formatting(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    pending = _mock_export(monkeypatch, secrets={"API_KEY": "secret value", "DEBUG": "true"})
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["export", "--format", "dotenv", "--path", "/backend", "--tag", "api", "--tag", "shared"],
    )

    assert result.exit_code == 0
    assert not pending
    assert result.output == 'API_KEY="secret value"\nDEBUG=true\n'


def test_export_supports_json_yaml_and_shell_rendering() -> None:
    secrets = {"API_KEY": "a b'c", "EMPTY": ""}

    assert json.loads(render_secret_payload(secrets, "json")) == secrets
    assert render_secret_payload(secrets, "yaml") == '"API_KEY": "a b\'c"\n"EMPTY": ""\n'
    assert render_secret_payload(secrets, "shell") == "export API_KEY='a b'\"'\"'c'\nexport EMPTY=''\n"


def test_export_writes_file_and_emits_json_metadata(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    pending = _mock_export(monkeypatch, secrets={"API_KEY": "secret"})
    destination = tmp_path / "out.json"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "--json",
            "export",
            "--format",
            "json",
            "--output",
            str(destination),
            "--path",
            "/backend",
            "--tag",
            "api",
            "--tag",
            "shared",
        ],
    )

    assert result.exit_code == 0
    assert not pending
    assert json.loads(destination.read_text(encoding="utf-8")) == {"API_KEY": "secret"}
    assert os.stat(destination).st_mode & 0o777 == 0o600
    payload = json.loads(result.output)
    assert payload["exported"] is True
    assert payload["count"] == 1


def test_export_json_mode_never_prompts_before_overwrite(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    pending = _mock_export(monkeypatch, secrets={"API_KEY": "replacement"})
    destination = tmp_path / "out.env"
    destination.write_text("ORIGINAL=yes\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "--json",
            "export",
            "--output",
            str(destination),
            "--path",
            "/backend",
            "--tag",
            "api",
            "--tag",
            "shared",
        ],
    )

    assert result.exit_code == 1
    assert not pending
    assert "Pass --overwrite" in result.output
    assert destination.read_text(encoding="utf-8") == "ORIGINAL=yes\n"


def test_shell_export_rejects_invalid_variable_names() -> None:
    try:
        render_secret_payload({"NOT-VALID": "secret"}, "shell")
    except ValueError as exc:
        assert "invalid shell variable name" in str(exc)
    else:
        raise AssertionError("Expected invalid shell variable name to be rejected")
