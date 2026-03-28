from __future__ import annotations

import httpx

from envbasis_cli.client import APIError, EnvBasisClient


class FakeAuthManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.clear_calls = 0

    def get_valid_access_token(self, api_url: str, *, force_refresh: bool = False) -> str:
        self.calls.append((api_url, force_refresh))
        return "access-refresh" if force_refresh else "access-live"

    def clear_session(self) -> None:
        self.clear_calls += 1


def test_client_uses_auth_manager_bearer_token(monkeypatch) -> None:
    auth_manager = FakeAuthManager()
    client = EnvBasisClient("https://api.example.com/api/v1", auth_manager)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers)
        assert headers["Authorization"] == "Bearer access-live"
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    payload = client.request("GET", "/projects")

    assert payload == {"ok": True}
    assert auth_manager.calls == [("https://api.example.com/api/v1", False)]


def test_client_retries_once_after_401_with_refreshed_token(monkeypatch) -> None:
    auth_manager = FakeAuthManager()
    client = EnvBasisClient("https://api.example.com/api/v1", auth_manager)
    calls = {"count": 0}

    def fake_request(self, method, url, params=None, json=None, headers=None):
        calls["count"] += 1
        request = httpx.Request(method, url, headers=headers)
        if calls["count"] == 1:
            assert headers["Authorization"] == "Bearer access-live"
            return httpx.Response(401, json={"detail": "Expired"}, request=request)
        assert headers["Authorization"] == "Bearer access-refresh"
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    payload = client.request("GET", "/projects")

    assert payload == {"ok": True}
    assert auth_manager.calls == [
        ("https://api.example.com/api/v1", False),
        ("https://api.example.com/api/v1", True),
    ]
    assert auth_manager.clear_calls == 0


def test_client_clears_session_after_repeated_401(monkeypatch) -> None:
    auth_manager = FakeAuthManager()
    client = EnvBasisClient("https://api.example.com/api/v1", auth_manager)

    def fake_request(self, method, url, params=None, json=None, headers=None):
        request = httpx.Request(method, url, headers=headers)
        return httpx.Response(401, json={"detail": "Still expired"}, request=request)

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    try:
        client.request("GET", "/projects")
    except APIError as exc:
        assert exc.status_code == 401
        assert "Still expired" in str(exc)
    else:
        raise AssertionError("Expected a repeated 401 to surface as APIError")

    assert auth_manager.calls == [
        ("https://api.example.com/api/v1", False),
        ("https://api.example.com/api/v1", True),
    ]
    assert auth_manager.clear_calls == 1
