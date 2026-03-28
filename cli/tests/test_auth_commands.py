from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from typer.testing import CliRunner

from envbasis_cli.auth import AuthManager, CliAuthSession
from envbasis_cli.config import ConfigManager
from envbasis_cli.main import app


class FakeKeyring:
    def __init__(self) -> None:
        self.value: str | None = None
        self.set_error: Exception | None = None

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.value

    def set_password(self, service_name: str, username: str, password: str) -> None:
        if self.set_error is not None:
            raise self.set_error
        self.value = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.value = None


def _wire_main_dependencies(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".envbasis.toml"
    monkeypatch.setattr("envbasis_cli.main.ConfigManager", lambda: ConfigManager(config_path))
    monkeypatch.setattr("envbasis_cli.main.TokenStore", AuthManager)


def _install_fake_keyring(monkeypatch, fake_keyring: FakeKeyring) -> None:
    monkeypatch.setattr("envbasis_cli.auth.keyring.get_password", fake_keyring.get_password)
    monkeypatch.setattr("envbasis_cli.auth.keyring.set_password", fake_keyring.set_password)
    monkeypatch.setattr("envbasis_cli.auth.keyring.delete_password", fake_keyring.delete_password)


def _serialize_session(session: CliAuthSession) -> str:
    return json.dumps(
        {
            "access_token": session.access_token.get_secret_value(),
            "refresh_token": session.refresh_token.get_secret_value(),
            "token_type": session.token_type,
            "expires_at": session.expires_at.isoformat(),
            "user_id": session.user_id,
            "email": session.email,
        }
    )


def test_login_prints_code_and_url_and_persists_session(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    opened: list[str] = []
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)

    def fake_open(url: str, new: int = 0) -> bool:
        opened.append(url)
        return True

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        if url == "https://api.example.com/api/v1/cli/auth/start":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://app.example.com/cli",
                    "verification_url_complete": "https://app.example.com/cli?code=ABCD-EFGH",
                    "expires_in": 600,
                    "interval": 5,
                },
                request=request,
            )
        if url == "https://api.example.com/api/v1/cli/auth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-live",
                    "refresh_token": "refresh-live",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "user": {"id": "user_123", "email": "dev@example.com"},
                },
                request=request,
            )
        assert url == "https://api.example.com/api/v1/auth/me"
        assert headers["Authorization"] == "Bearer access-live"
        return httpx.Response(200, json={"id": "user_123", "email": "dev@example.com"}, request=request)

    monkeypatch.setattr("envbasis_cli.commands.auth.webbrowser.open", fake_open)
    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "login"])

    assert result.exit_code == 0
    assert "Code: ABCD-EFGH" in result.output
    assert "https://app.example.com/cli?code=ABCD-EFGH" in result.output
    assert "Logged in as dev@example.com" in result.output
    assert opened == ["https://app.example.com/cli?code=ABCD-EFGH"]
    stored_session = json.loads(fake_keyring.value or "{}")
    assert stored_session["access_token"] == "access-live"
    assert stored_session["refresh_token"] == "refresh-live"
    assert stored_session["email"] == "dev@example.com"
    config_text = (tmp_path / ".envbasis.toml").read_text(encoding="utf-8")
    assert 'api_base_url = "https://api.example.com/api/v1"' in config_text


def test_login_continues_when_browser_open_fails(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    monkeypatch.setattr("envbasis_cli.commands.auth.webbrowser.open", lambda url, new=0: False)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        if url.endswith("/cli/auth/start"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://app.example.com/cli",
                    "expires_in": 600,
                    "interval": 5,
                },
                request=request,
            )
        if url.endswith("/cli/auth/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-live",
                    "refresh_token": "refresh-live",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "user": {"id": "user_123", "email": "dev@example.com"},
                },
                request=request,
            )
        return httpx.Response(200, json={"id": "user_123", "email": "dev@example.com"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "login"])

    assert result.exit_code == 0
    assert "https://app.example.com/cli" in result.output


def test_login_respects_pending_and_slow_down_intervals(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    sleeps: list[int] = []
    poll_count = {"count": 0}
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    monkeypatch.setattr("envbasis_cli.commands.auth.webbrowser.open", lambda url, new=0: True)
    monkeypatch.setattr("envbasis_cli.commands.auth.time.sleep", lambda seconds: sleeps.append(seconds))

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        if url.endswith("/cli/auth/start"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://app.example.com/cli",
                    "expires_in": 600,
                    "interval": 5,
                },
                request=request,
            )
        if url.endswith("/cli/auth/token"):
            poll_count["count"] += 1
            if poll_count["count"] == 1:
                return httpx.Response(202, json={"error": "authorization_pending", "interval": 5}, request=request)
            if poll_count["count"] == 2:
                return httpx.Response(429, json={"error": "slow_down", "interval": 7}, request=request)
            return httpx.Response(
                200,
                json={
                    "access_token": "access-live",
                    "refresh_token": "refresh-live",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "user": {"id": "user_123", "email": "dev@example.com"},
                },
                request=request,
            )
        return httpx.Response(200, json={"id": "user_123", "email": "dev@example.com"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "login"])

    assert result.exit_code == 0
    assert sleeps == [5, 7]


def test_login_surfaces_terminal_polling_failure(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    monkeypatch.setattr("envbasis_cli.commands.auth.webbrowser.open", lambda url, new=0: True)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        if url.endswith("/cli/auth/start"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://app.example.com/cli",
                    "expires_in": 600,
                    "interval": 5,
                },
                request=request,
            )
        return httpx.Response(410, json={"error": "expired_token"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "login"])

    assert result.exit_code == 1
    assert "Login session expired. Run envbasis login again." in result.output
    assert fake_keyring.value is None


def test_whoami_requires_login_before_api_resolution(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    runner = CliRunner()

    result = runner.invoke(app, ["whoami"])

    assert result.exit_code == 1
    assert "You are not logged in." in result.output


def test_whoami_refreshes_expired_session_and_returns_json(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    expired_session = CliAuthSession(
        access_token="stale-token",
        refresh_token="refresh-old",
        token_type="bearer",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        user_id="user_123",
        email="dev@example.com",
    )
    fake_keyring.value = _serialize_session(expired_session)
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        if url == "https://api.example.com/api/v1/cli/auth/refresh":
            assert json == {"refresh_token": "refresh-old"}
            return httpx.Response(
                200,
                json={
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
                request=request,
            )

        assert url == "https://api.example.com/api/v1/auth/me"
        assert headers["Authorization"] == "Bearer access-new"
        return httpx.Response(200, json={"id": "user_123", "email": "dev@example.com"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "--json", "whoami"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"id": "user_123", "email": "dev@example.com"}
    stored_session = json.loads(fake_keyring.value or "{}")
    assert stored_session["access_token"] == "access-new"
    assert stored_session["refresh_token"] == "refresh-new"


def test_logout_clears_session_even_when_backend_revoke_fails(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    fake_keyring.value = _serialize_session(
        CliAuthSession(
            access_token="access-live",
            refresh_token="refresh-live",
            token_type="bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            user_id="user_123",
            email="dev@example.com",
        )
    )
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        assert url == "https://api.example.com/api/v1/cli/auth/logout"
        assert json == {"refresh_token": "refresh-live"}
        return httpx.Response(500, json={"detail": "backend-error"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "--json", "logout"])

    assert result.exit_code == 0
    assert fake_keyring.value is None
    assert json.loads(result.output) == {"authenticated": False}


def test_whoami_uses_api_url_from_environment(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    fake_keyring.value = _serialize_session(
        CliAuthSession(
            access_token="live-token",
            refresh_token="refresh-live",
            token_type="bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            user_id="user_789",
            email="env@example.com",
        )
    )
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    monkeypatch.setenv("ENVBASIS_API_URL", "https://api.example.com/api/v1")

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers)
        assert url == "https://api.example.com/api/v1/auth/me"
        assert headers["Authorization"] == "Bearer live-token"
        return httpx.Response(200, json={"id": "user_789", "email": "env@example.com"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"id": "user_789", "email": "env@example.com"}


def test_explicit_flag_wins_over_api_url_environment_variable(monkeypatch, tmp_path) -> None:
    fake_keyring = FakeKeyring()
    fake_keyring.value = _serialize_session(
        CliAuthSession(
            access_token="live-token",
            refresh_token="refresh-live",
            token_type="bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            user_id="user_456",
            email="ops@example.com",
        )
    )
    _wire_main_dependencies(monkeypatch, tmp_path)
    _install_fake_keyring(monkeypatch, fake_keyring)
    monkeypatch.setenv("ENVBASIS_API_URL", "https://ignored.example.com/api/v1")

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers)
        assert url == "https://api.example.com/api/v1/auth/me"
        assert headers["Authorization"] == "Bearer live-token"
        return httpx.Response(200, json={"id": "user_456", "email": "ops@example.com"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["--api-url", "https://api.example.com/api/v1", "--json", "whoami"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"id": "user_456", "email": "ops@example.com"}
