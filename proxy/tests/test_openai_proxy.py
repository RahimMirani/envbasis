from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from conftest import OPENAI_KEY, UpstreamRecorder


def test_valid_response_request_is_forwarded_with_provider_key(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/openai/v1/responses",
        headers=auth_headers,
        json={"model": "gpt-5.6-terra", "input": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(recorder.requests) == 1
    upstream = recorder.requests[0]
    assert upstream.url == httpx.URL("https://api.openai.com/v1/responses")
    assert upstream.headers["authorization"] == f"Bearer {OPENAI_KEY}"
    assert auth_headers["Authorization"] not in upstream.headers.values()


def test_openai_request_must_have_model(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/openai/v1/responses",
        headers=auth_headers,
        json={"input": "hello"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert recorder.requests == []


def test_openai_administration_is_blocked(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/openai/v1/organization/api_keys", headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "operation_blocked"
    assert recorder.requests == []


def test_openai_unknown_endpoint_is_default_denied(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/openai/v1/fine_tuning/jobs",
        headers=auth_headers,
        json={"model": "example"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unsupported_operation"
    assert recorder.requests == []


def test_provider_redirect_is_not_followed(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    recorder.response_status = 302
    recorder.response_headers = {"Location": "https://attacker.example/collect"}

    response = client.get("/openai/v1/models", headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream_redirect_blocked"
    assert len(recorder.requests) == 1


def test_provider_key_is_redacted_from_response(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    recorder.response_body = f'{{"unexpected":"{OPENAI_KEY}"}}'.encode()

    response = client.get("/openai/v1/models", headers=auth_headers)

    assert response.status_code == 200
    assert OPENAI_KEY not in response.text
    assert "REDACTED_CREDENTIAL" in response.text

