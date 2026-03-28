from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeTokenStore:
    def __init__(self) -> None:
        self.token: str | None = "secret-token"

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


def test_push_uploads_dotenv_file(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("OPENAI_API_KEY=sk-test\nDEBUG=true\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/push",
                "json": {
                    "secrets": {
                        "OPENAI_API_KEY": "sk-test",
                        "DEBUG": "true",
                    }
                },
                "status_code": 200,
                "payload": {
                    "changed": 1,
                    "unchanged": 1,
                    "changed_keys": ["OPENAI_API_KEY"],
                    "unchanged_keys": ["DEBUG"],
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--file", str(dotenv_path)])

    assert result.exit_code == 0
    assert "Pushed 1 changed secrets, 1 unchanged" in result.output


def test_push_review_shows_masked_diff_and_pushes_after_confirmation(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("DEBUG=true\nNEW_SECRET=local-new\nOPENAI_API_KEY=local-key\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "DEBUG": "true",
                        "OPENAI_API_KEY": "remote-key",
                        "REMOTE_ONLY": "remote-value",
                    },
                },
                "auth": "secret-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/push",
                "json": {
                    "secrets": {
                        "DEBUG": "true",
                        "NEW_SECRET": "local-new",
                        "OPENAI_API_KEY": "local-key",
                    }
                },
                "status_code": 200,
                "payload": {
                    "changed": 2,
                    "unchanged": 1,
                    "changed_keys": ["NEW_SECRET", "OPENAI_API_KEY"],
                    "unchanged_keys": ["DEBUG"],
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--file", str(dotenv_path), "--review"], input="y\n")

    assert result.exit_code == 0
    assert "--- remote" in result.output
    assert "+++ local" in result.output
    assert "DEBUG=<unchanged hidden>" in result.output
    assert "- OPENAI_API_KEY=<remote value hidden>" in result.output
    assert "+ OPENAI_API_KEY=<local value hidden>" in result.output
    assert "+ NEW_SECRET=<local value hidden>" in result.output
    assert "- REMOTE_ONLY=<remote-only, not deleted>" in result.output
    assert "Apply this push?" in result.output
    assert "Pushed 2 changed secrets, 1 unchanged" in result.output


def test_push_review_aborts_when_confirmation_is_declined(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("OPENAI_API_KEY=local-key\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "OPENAI_API_KEY": "remote-key",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--file", str(dotenv_path), "--review"], input="n\n")

    assert result.exit_code == 1
    assert "Apply this push?" in result.output
    assert "Aborted." in result.output


def test_push_review_yes_skips_confirmation_prompt(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("OPENAI_API_KEY=local-key\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "OPENAI_API_KEY": "remote-key",
                    },
                },
                "auth": "secret-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/push",
                "json": {
                    "secrets": {
                        "OPENAI_API_KEY": "local-key",
                    }
                },
                "status_code": 200,
                "payload": {
                    "changed": 1,
                    "unchanged": 0,
                    "changed_keys": ["OPENAI_API_KEY"],
                    "unchanged_keys": [],
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--file", str(dotenv_path), "--review", "--yes"])

    assert result.exit_code == 0
    assert "Apply this push?" not in result.output
    assert "Pushed 1 changed secrets, 0 unchanged" in result.output


def test_push_review_no_changes_skips_push_request(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("DEBUG=true\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "DEBUG": "true",
                        "REMOTE_ONLY": "remote-value",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--file", str(dotenv_path), "--review"])

    assert result.exit_code == 0
    assert "DEBUG=<unchanged hidden>" in result.output
    assert "- REMOTE_ONLY=<remote-only, not deleted>" in result.output
    assert "No changes to push." in result.output
    assert "Apply this push?" not in result.output


def test_push_yes_without_review_errors(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    _wire_main_dependencies(monkeypatch, tmp_path, token_store)
    runner = CliRunner()

    result = runner.invoke(app, ["push", "--yes"])

    assert result.exit_code == 1
    assert "--yes can only be used with --review." in result.output
    assert "Did you mean: envbasis push --review" in result.output
    assert "--yes?" in result.output


def test_pull_stdout_json_uses_saved_environment(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    config_path.write_text(
        'api_base_url = "https://api.example.com/api/v1"\nproject_id = "proj_1"\nproject_name = "my-ai-app"\nenvironment = "prod"\n',
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [
                    {"id": "env_1", "name": "dev"},
                    {"id": "env_2", "name": "prod"},
                ],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_2/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_2",
                    "environment_name": "prod",
                    "secrets": {
                        "OPENAI_API_KEY": "sk-test",
                        "DEBUG": "true",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["pull", "--stdout", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"DEBUG": "true", "OPENAI_API_KEY": "sk-test"}


def test_pull_writes_dotenv_file_when_confirmed(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    output_path = tmp_path / ".env"
    output_path.write_text("OLD=value\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "DEBUG": "true value",
                        "OPENAI_API_KEY": "sk-test",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["pull", "--file", str(output_path)], input="y\n")

    assert result.exit_code == 0
    assert output_path.read_text(encoding="utf-8") == 'DEBUG="true value"\nOPENAI_API_KEY=sk-test\n'


def test_pull_aborts_when_overwrite_is_declined(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    output_path = tmp_path / ".env"
    output_path.write_text("OLD=value\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "OPENAI_API_KEY": "sk-test",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["pull", "--file", str(output_path)], input="n\n")

    assert result.exit_code == 1
    assert output_path.read_text(encoding="utf-8") == "OLD=value\n"
    assert "Aborted." in result.output


def test_pull_overwrite_skips_prompt(monkeypatch, tmp_path) -> None:
    token_store = FakeTokenStore()
    config_path = tmp_path / ".envbasis.toml"
    output_path = tmp_path / ".env"
    output_path.write_text("OLD=value\n", encoding="utf-8")
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/pull",
                "status_code": 200,
                "payload": {
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "secrets": {
                        "OPENAI_API_KEY": "sk-overwrite",
                    },
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["pull", "--file", str(output_path), "--overwrite"])

    assert result.exit_code == 0
    assert output_path.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-overwrite\n"
    assert "Overwrite it?" not in result.output


def test_secrets_list_hides_values_by_default(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets",
                "status_code": 200,
                "payload": [
                    {
                        "key": "OPENAI_API_KEY",
                        "version": 3,
                        "updated_at": "2026-03-15T10:00:00Z",
                        "updated_by": "dev@example.com",
                        "value": "sk-secret",
                    }
                ],
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "list"])

    assert result.exit_code == 0
    assert "OPENAI_API_KEY" in result.output
    assert "sk-secret" not in result.output


def test_secrets_list_accepts_wrapped_backend_payload(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets",
                "status_code": 200,
                "payload": {
                    "project_id": "proj_1",
                    "environment_id": "env_1",
                    "environment_name": "dev",
                    "retrieved_at": "2026-03-15T20:33:03.493713Z",
                    "secrets": [
                        {
                            "key": "OPENAI_API_KEY",
                            "version": 3,
                            "updated_at": "2026-03-15T10:00:00Z",
                            "updated_by": "dev@example.com",
                            "value": "sk-secret",
                        }
                    ],
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "secrets", "list"])

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {
            "key": "OPENAI_API_KEY",
            "version": 3,
            "updated_at": "2026-03-15T10:00:00Z",
            "updated_by": "dev@example.com",
            "value": "sk-secret",
        }
    ]


def test_secrets_stats_emits_json(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/secrets/stats",
                "status_code": 200,
                "payload": {
                    "project_id": "proj_1",
                    "total_secret_count": 6,
                    "environments": [
                        {
                            "environment_id": "env_1",
                            "environment_name": "dev",
                            "secret_count": 4,
                            "last_updated_at": "2026-03-15T10:00:00Z",
                            "last_activity_at": "2026-03-15T10:00:00Z",
                        },
                        {
                            "environment_id": "env_2",
                            "environment_name": "prod",
                            "secret_count": 2,
                            "last_updated_at": "2026-03-15T11:00:00Z",
                            "last_activity_at": "2026-03-15T11:00:00Z",
                        },
                    ],
                    "generated_at": "2026-03-15T12:00:00Z",
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "secrets", "stats"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_secret_count"] == 6
    assert payload["generated_at"] == "2026-03-15T12:00:00Z"
    assert payload["environments"][0]["environment_name"] == "dev"
    assert payload["environments"][0]["secret_count"] == 4


def test_secrets_stats_renders_project_total_from_backend_contract(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/secrets/stats",
                "status_code": 200,
                "payload": {
                    "project_id": "proj_1",
                    "total_secret_count": 5,
                    "environments": [
                        {
                            "environment_id": "env_1",
                            "environment_name": "dev",
                            "secret_count": 5,
                            "last_updated_at": "2026-03-15T10:00:00Z",
                            "last_activity_at": "2026-03-15T10:00:00Z",
                        }
                    ],
                    "generated_at": "2026-03-15T12:00:00Z",
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "stats"])

    assert result.exit_code == 0
    assert "Total secrets: 5" in result.output
    assert "dev" in result.output


def test_secrets_set_posts_single_secret(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "POST",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets",
                "json": {"key": "OPENAI_API_KEY", "value": "sk-test"},
                "status_code": 200,
                "payload": {
                    "key": "OPENAI_API_KEY",
                    "version": 1,
                    "updated_by": "dev@example.com",
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "set", "OPENAI_API_KEY", "sk-test"])

    assert result.exit_code == 0
    assert "Set secret OPENAI_API_KEY" in result.output


def test_secrets_update_patches_single_secret(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "PATCH",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/OPENAI_API_KEY",
                "json": {"value": "sk-new"},
                "status_code": 200,
                "payload": {
                    "key": "OPENAI_API_KEY",
                    "version": 2,
                    "updated_by": "dev@example.com",
                },
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "update", "OPENAI_API_KEY", "sk-new"])

    assert result.exit_code == 0
    assert "Updated secret OPENAI_API_KEY" in result.output


def test_secrets_delete_removes_single_secret(monkeypatch, tmp_path) -> None:
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
                "auth": "secret-token",
            },
            {
                "method": "GET",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments",
                "status_code": 200,
                "payload": [{"id": "env_1", "name": "dev"}],
                "auth": "secret-token",
            },
            {
                "method": "DELETE",
                "url": "https://api.example.com/api/v1/projects/proj_1/environments/env_1/secrets/OPENAI_API_KEY",
                "status_code": 204,
                "payload": None,
                "auth": "secret-token",
            },
        ],
    )
    runner = CliRunner()

    result = runner.invoke(app, ["secrets", "delete", "OPENAI_API_KEY"])

    assert result.exit_code == 0
    assert "Deleted secret OPENAI_API_KEY" in result.output
