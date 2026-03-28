from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from keyring.errors import KeyringError

from envbasis_cli.auth import (
    AuthError,
    AuthManager,
    CliAuthSession,
    CliAuthStartRequest,
)


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


def _install_fake_keyring(monkeypatch, fake_keyring: FakeKeyring) -> None:
    monkeypatch.setattr("envbasis_cli.auth.keyring.get_password", fake_keyring.get_password)
    monkeypatch.setattr("envbasis_cli.auth.keyring.set_password", fake_keyring.set_password)
    monkeypatch.setattr("envbasis_cli.auth.keyring.delete_password", fake_keyring.delete_password)


def _session(
    *,
    access_token: str = "access-live",
    refresh_token: str = "refresh-live",
    expires_at: datetime | None = None,
) -> CliAuthSession:
    return CliAuthSession(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(hours=1),
        user_id="user_123",
        email="dev@example.com",
    )


def test_auth_manager_save_and_load_session_round_trip(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)

    auth_manager.save_session(_session())
    restored = auth_manager.load_session()

    assert restored is not None
    assert restored.access_token.get_secret_value() == "access-live"
    assert restored.refresh_token.get_secret_value() == "refresh-live"
    assert restored.user_id == "user_123"


def test_start_device_login_returns_backend_payload(monkeypatch) -> None:
    auth_manager = AuthManager()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        assert method == "POST"
        assert url == "https://api.example.com/api/v1/cli/auth/start"
        assert json["client_name"] == "envbasis-cli"
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

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    start = auth_manager.start_device_login(
        "https://api.example.com/api/v1",
        CliAuthStartRequest(
            client_name="envbasis-cli",
            device_name="Ali's MacBook Air",
            cli_version="0.1.0",
            platform="darwin-arm64",
        ),
    )

    assert start.device_code == "device-code"
    assert start.user_code == "ABCD-EFGH"
    assert str(start.verification_url_complete) == "https://app.example.com/cli?code=ABCD-EFGH"


def test_poll_for_session_returns_pending_status(monkeypatch) -> None:
    auth_manager = AuthManager()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        return httpx.Response(202, json={"error": "authorization_pending", "interval": 5}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    result = auth_manager.poll_for_session("https://api.example.com/api/v1", "device-code")

    assert result.status_code == 202
    assert result.error == "authorization_pending"
    assert result.interval == 5
    assert result.session is None


def test_poll_for_session_returns_completed_session(monkeypatch) -> None:
    auth_manager = AuthManager()

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
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

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    result = auth_manager.poll_for_session("https://api.example.com/api/v1", "device-code")

    assert result.status_code == 200
    assert result.session is not None
    assert result.session.access_token.get_secret_value() == "access-live"
    assert result.user is not None
    assert result.user.email == "dev@example.com"


def test_refresh_session_persists_new_tokens(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)
    auth_manager.save_session(_session(refresh_token="refresh-old"))

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        assert url == "https://api.example.com/api/v1/cli/auth/refresh"
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

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    refreshed = auth_manager.refresh_session("https://api.example.com/api/v1")

    assert refreshed.access_token.get_secret_value() == "access-new"
    assert refreshed.refresh_token.get_secret_value() == "refresh-new"
    stored_payload = json.loads(fake_keyring.value or "{}")
    assert stored_payload["access_token"] == "access-new"
    assert stored_payload["refresh_token"] == "refresh-new"


def test_refresh_failure_clears_session_and_requires_login(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)
    auth_manager.save_session(_session(refresh_token="refresh-old"))

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
        return httpx.Response(403, json={"detail": "access_denied"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    try:
        auth_manager.refresh_session("https://api.example.com/api/v1")
    except AuthError as exc:
        assert "Run envbasis login again." in str(exc)
    else:
        raise AssertionError("Expected refresh_session to fail when the backend rejects the refresh token")

    assert fake_keyring.value is None


def test_get_valid_access_token_refreshes_when_expired(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)
    auth_manager.save_session(_session(refresh_token="refresh-old", expires_at=datetime.now(timezone.utc)))

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers, json=json)
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

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    token = auth_manager.get_valid_access_token("https://api.example.com/api/v1")

    assert token == "access-new"


def test_auth_manager_save_session_surfaces_keyring_errors(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    fake_keyring.set_error = KeyringError("No recommended backend")
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)

    try:
        auth_manager.save_session(_session())
    except AuthError as exc:
        assert "Failed to store auth session in keyring" in str(exc)
    else:
        raise AssertionError("Expected save_session to surface keyring write errors")


def test_auth_manager_load_session_rejects_invalid_payload(monkeypatch) -> None:
    fake_keyring = FakeKeyring()
    fake_keyring.value = json.dumps({"access_token": "missing-fields"})
    auth_manager = AuthManager()
    _install_fake_keyring(monkeypatch, fake_keyring)

    try:
        auth_manager.load_session()
    except AuthError as exc:
        assert "Stored auth session is invalid" in str(exc)
    else:
        raise AssertionError("Expected invalid stored sessions to be rejected")
