from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from conftest import ANTHROPIC_KEY, UpstreamRecorder


def test_anthropic_messages_uses_x_api_key(
    client: TestClient,
    recorder: UpstreamRecorder,
    machine_token: str,
) -> None:
    response = client.post(
        "/anthropic/v1/messages",
        headers={"x-api-key": machine_token, "anthropic-version": "2023-06-01"},
        json={
            "model": "claude-sonnet-4-5",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
    )

    assert response.status_code == 200
    assert len(recorder.requests) == 1
    upstream = recorder.requests[0]
    assert upstream.url == httpx.URL("https://api.anthropic.com/v1/messages")
    assert upstream.headers["x-api-key"] == ANTHROPIC_KEY
    assert "authorization" not in upstream.headers
    assert upstream.headers["anthropic-version"] == "2023-06-01"
    assert machine_token not in upstream.headers.values()


def test_anthropic_unknown_endpoint_is_denied(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/anthropic/v1/complete",
        headers=auth_headers,
        json={"model": "claude-sonnet-4-5", "prompt": "hello"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unsupported_operation"
    assert recorder.requests == []
