from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from conftest import MACHINE_SECRET, OPENAI_KEY, UpstreamRecorder, issue_machine_token
from envbasis_proxy.config import ProxySettings
from envbasis_proxy.main import create_app


PLATFORM_OPENAI_KEY = "sk-platform-stored-openai-key"
CONTROL_PLANE_TOKEN = "test-proxy-service-token"
CONTROL_PLANE_HOST = "control-plane.test"


def _control_plane_settings(**overrides: object) -> ProxySettings:
    values: dict[str, object] = {
        "machine_auth_jwt_secret": MACHINE_SECRET,
        "control_plane_url": f"https://{CONTROL_PLANE_HOST}",
        "proxy_service_token": CONTROL_PLANE_TOKEN,
        "openai_upstream_url": "https://api.openai.com",
        "github_upstream_url": "https://api.github.com",
        "anthropic_upstream_url": "https://api.anthropic.com",
        "max_request_bytes": 4096,
        "max_response_bytes": 4096,
    }
    values.update(overrides)
    return ProxySettings(**values)  # type: ignore[arg-type]


def test_control_plane_key_is_injected_instead_of_env(recorder: UpstreamRecorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == CONTROL_PLANE_HOST:
            payload = json.loads(request.content.decode())
            assert payload["provider"] == "openai"
            assert request.headers["authorization"] == f"Bearer {CONTROL_PLANE_TOKEN}"
            return httpx.Response(
                200,
                json={"provider": "openai", "secret": PLATFORM_OPENAI_KEY},
                request=request,
            )
        return recorder.handler(request)

    token = issue_machine_token(actions=["proxy:use"])
    settings = _control_plane_settings(openai_api_key=OPENAI_KEY)
    app = create_app(settings, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    assert len(recorder.requests) == 1
    assert recorder.requests[0].headers["authorization"] == f"Bearer {PLATFORM_OPENAI_KEY}"
    assert OPENAI_KEY not in recorder.requests[0].headers["authorization"]


def test_control_plane_missing_key_returns_503(recorder: UpstreamRecorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == CONTROL_PLANE_HOST:
            return httpx.Response(404, json={"detail": "missing"}, request=request)
        return recorder.handler(request)

    token = issue_machine_token(actions=["proxy:use"])
    app = create_app(_control_plane_settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_not_configured"
    assert recorder.requests == []


def test_control_plane_requires_proxy_use_action(recorder: UpstreamRecorder) -> None:
    token = issue_machine_token(actions=["secrets:read"])
    app = create_app(_control_plane_settings(), transport=httpx.MockTransport(recorder.handler))
    with TestClient(app) as client:
        response = client.post(
            "/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "proxy_use_forbidden"
    assert recorder.requests == []
