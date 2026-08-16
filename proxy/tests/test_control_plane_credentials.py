from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from conftest import MACHINE_SECRET, UpstreamRecorder
from envbasis_proxy.config import ProxySettings
from envbasis_proxy.credentials import credential_resolver
from envbasis_proxy.main import create_app


CONTROL_PLANE_KEY = "sk-control-plane-openai-key"
PROXY_SERVICE_TOKEN = "proxy-service-token"


def test_proxy_injects_control_plane_credential(
    recorder: UpstreamRecorder,
    machine_token: str,
) -> None:
    credential_resolver.clear()
    control_plane_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "control-plane.test":
            control_plane_calls.append(request)
            assert request.headers["authorization"] == f"Bearer {PROXY_SERVICE_TOKEN}"
            body = json.loads(request.content.decode("utf-8"))
            assert body["provider"] == "openai"
            assert body["machine_access_token"] == machine_token
            return httpx.Response(
                200,
                json={
                    "provider": "openai",
                    "credential": CONTROL_PLANE_KEY,
                    "project_id": "11111111-1111-1111-1111-111111111111",
                    "environment_id": "22222222-2222-2222-2222-222222222222",
                    "machine_identity_id": "33333333-3333-3333-3333-333333333333",
                    "credential_version": 7,
                },
                request=request,
            )
        return recorder.handler(request)

    settings = ProxySettings(
        machine_auth_jwt_secret=MACHINE_SECRET,
        control_plane_url="https://control-plane.test",
        proxy_service_token=PROXY_SERVICE_TOKEN,
        openai_upstream_url="https://api.openai.com",
        anthropic_upstream_url="https://api.anthropic.com",
        github_upstream_url="https://api.github.com",
        max_request_bytes=4096,
        max_response_bytes=4096,
        credential_cache_ttl_seconds=60,
    )
    app = create_app(settings, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/openai/v1/responses",
            headers={"Authorization": f"Bearer {machine_token}"},
            json={"model": "gpt-5.6-terra", "input": "hello"},
        )
        assert response.status_code == 200
        # Second request should hit cache and not re-call control plane.
        second = client.post(
            "/openai/v1/responses",
            headers={"Authorization": f"Bearer {machine_token}"},
            json={"model": "gpt-5.6-terra", "input": "again"},
        )
        assert second.status_code == 200

    assert len(control_plane_calls) == 1
    assert len(recorder.requests) == 2
    assert recorder.requests[0].headers["authorization"] == f"Bearer {CONTROL_PLANE_KEY}"
    assert machine_token not in recorder.requests[0].headers.values()


def test_control_plane_missing_provider_returns_503(machine_token: str) -> None:
    credential_resolver.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "control-plane.test":
            return httpx.Response(
                404,
                json={
                    "detail": {
                        "code": "provider_not_configured",
                        "message": "No openai credential is configured for this environment.",
                    }
                },
                request=request,
            )
        return httpx.Response(500, request=request)

    settings = ProxySettings(
        machine_auth_jwt_secret=MACHINE_SECRET,
        control_plane_url="https://control-plane.test",
        proxy_service_token=PROXY_SERVICE_TOKEN,
        openai_upstream_url="https://api.openai.com",
        anthropic_upstream_url="https://api.anthropic.com",
        github_upstream_url="https://api.github.com",
        max_request_bytes=4096,
        max_response_bytes=4096,
    )
    app = create_app(settings, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/openai/v1/models",
            headers={"Authorization": f"Bearer {machine_token}"},
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_not_configured"
