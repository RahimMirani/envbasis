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
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nenvironment = "prod"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", FakeTokenStore)


def _context() -> list[dict[str, object]]:
    return [
        {"method": "GET", "url": "https://api.example.com/api/v1/projects", "payload": [{"id": "proj_1", "name": "demo"}]},
        {"method": "GET", "url": "https://api.example.com/api/v1/projects/proj_1/environments", "payload": [{"id": "env_1", "name": "prod"}]},
    ]


def _mock(monkeypatch, expected: list[dict[str, object]]) -> None:
    pending = expected.copy()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        item = pending.pop(0)
        assert (method, url) == (item["method"], item["url"])
        assert params == item.get("params")
        assert json == item.get("json")
        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(int(item.get("status", 200)), json=item.get("payload"), request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def test_history_list_and_historical_reveal(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock(
        monkeypatch,
        _context()
        + [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/TOKEN/versions",
                "params": {"path": "/api", "include_archived": True},
                "payload": {
                    "project_id": "proj_1",
                    "environment_id": "env_1",
                    "key": "TOKEN",
                    "path": "/api",
                    "versions": [
                        {"key": "TOKEN", "path": "/api", "version": 2, "updated_at": "2026-08-08T00:00:00Z", "updated_by_email": "owner@example.com"}
                    ],
                },
            }
        ],
    )
    listed = CliRunner().invoke(app, ["history", "list", "TOKEN", "--path", "/api"])
    assert listed.exit_code == 0
    assert "owner@example.com" in listed.output

    _mock(
        monkeypatch,
        _context()
        + [
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/TOKEN/versions/1/reveal",
                "params": {"path": "/api"},
                "payload": {"key": "TOKEN", "path": "/api", "version": 1, "updated_at": "2026-08-07T00:00:00Z", "value": "historical"},
            }
        ],
    )
    revealed = CliRunner().invoke(app, ["history", "reveal", "TOKEN", "1", "--path", "/api"])
    assert revealed.exit_code == 0
    assert revealed.output == "historical\n"


def test_history_rollback_requires_confirmation_and_reports_new_version(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock(
        monkeypatch,
        _context()
        + [
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/TOKEN/versions/1/rollback",
                "params": {"path": "/api"},
                "payload": {"key": "TOKEN", "path": "/api", "source_version": 1, "version": 3},
            }
        ],
    )
    result = CliRunner().invoke(
        app, ["history", "rollback", "TOKEN", "1", "--path", "/api", "--yes"]
    )
    assert result.exit_code == 0
    assert "Created version 3 from version 1" in result.output


def test_recovery_defaults_to_dry_run_and_retention_is_scriptable(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    _mock(
        monkeypatch,
        _context()
        + [
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/recovery",
                "json": {"at": "2026-08-01T00:00:00Z", "path": "/", "recursive": True, "dry_run": True},
                "payload": {"project_id": "proj_1", "environment_id": "env_1", "at": "2026-08-01T00:00:00Z", "dry_run": True, "changed": 2, "environments_changed": 1},
            }
        ],
    )
    preview = CliRunner().invoke(
        app, ["history", "recover", "--at", "2026-08-01T00:00:00Z", "--recursive"]
    )
    assert preview.exit_code == 0
    assert "Would change 2 secret(s)" in preview.output

    _mock(
        monkeypatch,
        [
            _context()[0],
            {
                "method": "PATCH",
                "url": "https://api.example.com/api/v1/projects/proj_1/secret-retention",
                "json": {"retain_versions": 20, "retain_days": 365, "archive_deleted_after_days": 30},
                "payload": {"project_id": "proj_1", "retain_versions": 20, "retain_days": 365, "archive_deleted_after_days": 30},
            },
        ],
    )
    retained = CliRunner().invoke(
        app,
        ["--json", "retention", "set", "--versions", "20", "--days", "365", "--archive-deleted-after", "30"],
    )
    assert retained.exit_code == 0
    assert json.loads(retained.output)["retain_versions"] == 20
