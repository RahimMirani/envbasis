from __future__ import annotations

import json
import os

import httpx
import pytest
from typer.testing import CliRunner

from envbasis_cli.config import ConfigError, ConfigManager, LocalConfig
from envbasis_cli.main import app


class FakeTokenStore:
    def get(self) -> str:
        return "config-token"


def _wire_main_dependencies(monkeypatch, config_manager: ConfigManager) -> None:
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: config_manager)
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)


def _mock_http(monkeypatch, responses: list[dict[str, object]]) -> list[dict[str, object]]:
    pending = responses.copy()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        assert pending, f"Unexpected request: {method} {url}"
        expected = pending.pop(0)
        assert method == expected["method"]
        assert url == expected["url"]
        assert headers is not None
        assert headers["Authorization"] == "Bearer config-token"
        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(
            int(expected["status_code"]),
            json=expected["payload"],
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return pending


def test_config_manager_finds_nearest_parent_configuration(tmp_path) -> None:
    repository = tmp_path / "repository"
    nested = repository / "apps" / "backend" / "src"
    nested.mkdir(parents=True)
    root_config = repository / ".envbasis.toml"
    root_config.write_text('config_version = 1\nproject_name = "root-project"\n', encoding="utf-8")
    nearer_config = repository / "apps" / ".envbasis.toml"
    nearer_config.write_text('config_version = 1\nproject_name = "apps-project"\n', encoding="utf-8")

    manager = ConfigManager(start_dir=nested)

    assert manager.path == nearer_config
    assert manager.load().project_name == "apps-project"


def test_config_manager_uses_starting_directory_when_no_parent_config_exists(tmp_path) -> None:
    nested = tmp_path / "repository" / "apps" / "backend"
    nested.mkdir(parents=True)

    manager = ConfigManager(start_dir=nested)

    assert manager.path == nested / ".envbasis.toml"
    assert manager.load().config_version == 1


def test_migration_creates_backup_and_upgrades_legacy_config(tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    original = (
        'api_base_url = "https://api.example.com/api/v1"\n'
        'project_id = "proj_1"\n'
        'project_name = "agent-api"\n'
        'environment = "dev"\n'
    )
    config_path.write_text(original, encoding="utf-8")
    manager = ConfigManager(config_path)

    result = manager.migrate()

    assert result.migrated is True
    assert result.old_version == 0
    assert result.new_version == 1
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert os.stat(result.backup_path).st_mode & 0o777 == 0o600
    assert manager.load().config_version == 1
    assert "config_version = 1" in config_path.read_text(encoding="utf-8")
    assert os.stat(config_path).st_mode & 0o777 == 0o600


def test_migration_is_a_noop_for_current_config(tmp_path) -> None:
    manager = ConfigManager(tmp_path / ".envbasis.toml")
    manager.save(LocalConfig(project_id="proj_1", project_name="agent-api", environment="dev"))

    result = manager.migrate()

    assert result.migrated is False
    assert result.backup_path is None
    assert not list(tmp_path.glob("*.bak"))


def test_atomic_save_preserves_original_when_replace_fails(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    original = 'config_version = 1\nproject_name = "original"\n'
    config_path.write_text(original, encoding="utf-8")
    manager = ConfigManager(config_path)

    def fail_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("envbasis_cli.config.os.replace", fail_replace)

    with pytest.raises(ConfigError, match="Could not save configuration"):
        manager.save(LocalConfig(project_name="replacement"))

    assert config_path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_config_check_validates_file_api_auth_project_and_environment(monkeypatch, tmp_path) -> None:
    api_url = "https://api.example.com/api/v1"
    manager = ConfigManager(tmp_path / ".envbasis.toml")
    manager.save(
        LocalConfig(
            api_base_url=api_url,
            project_id="proj_1",
            project_name="agent-api",
            environment="dev",
        )
    )
    _wire_main_dependencies(monkeypatch, manager)
    pending = _mock_http(
        monkeypatch,
        [
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
                "payload": [{"id": "proj_1", "name": "agent-api"}],
            },
            {
                "method": "GET",
                "url": f"{api_url}/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "config", "check"])

    assert result.exit_code == 0
    assert not pending
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert [check["name"] for check in payload["checks"]] == [
        "configuration_file",
        "configuration_syntax",
        "configuration_version",
        "api_url",
        "authentication",
        "project",
        "environment",
    ]


def test_config_check_reports_malformed_toml_without_changing_it(monkeypatch, tmp_path) -> None:
    manager = ConfigManager(tmp_path / ".envbasis.toml")
    malformed = 'api_base_url = "unterminated\n'
    manager.path.write_text(malformed, encoding="utf-8")
    _wire_main_dependencies(monkeypatch, manager)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "config", "check"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["valid"] is False
    assert payload["checks"][-1]["name"] == "configuration_syntax"
    assert manager.path.read_text(encoding="utf-8") == malformed


def test_config_migrate_command_reports_backup(monkeypatch, tmp_path) -> None:
    manager = ConfigManager(tmp_path / ".envbasis.toml")
    manager.path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_name = "agent-api"\n',
        encoding="utf-8",
    )
    _wire_main_dependencies(monkeypatch, manager)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "config", "migrate"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["migrated"] is True
    assert payload["old_version"] == 0
    assert payload["new_version"] == 1
    assert payload["backup_path"].endswith(".envbasis.toml.v0.bak")


def test_config_check_reports_stale_project_selection(monkeypatch, tmp_path) -> None:
    api_url = "https://api.example.com/api/v1"
    manager = ConfigManager(tmp_path / ".envbasis.toml")
    manager.save(
        LocalConfig(
            api_base_url=api_url,
            project_id="proj_deleted",
            project_name="deleted-project",
            environment="dev",
        )
    )
    _wire_main_dependencies(monkeypatch, manager)
    pending = _mock_http(
        monkeypatch,
        [
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
                "payload": [],
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "config", "check"])

    assert result.exit_code == 1
    assert not pending
    payload = json.loads(result.output)
    assert payload["valid"] is False
    assert payload["checks"][-1]["name"] == "project"
    assert "no longer exists" in payload["checks"][-1]["guidance"]
