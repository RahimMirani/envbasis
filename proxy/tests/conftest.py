from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any
import uuid

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("MACHINE_AUTH_JWT_SECRET", "test-machine-jwt-secret-that-is-long-enough")

from envbasis_proxy.config import ProxySettings  # noqa: E402
from envbasis_proxy.main import create_app  # noqa: E402


MACHINE_SECRET = "test-machine-jwt-secret-that-is-long-enough"
OPENAI_KEY = "sk-test-openai-provider-key"
GITHUB_TOKEN = "github_pat_test_provider_token"


def issue_machine_token(**overrides: Any) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "client_id": "envb_mi_test",
        "project_id": str(uuid.uuid4()),
        "organization_id": None,
        "environment_id": str(uuid.uuid4()),
        "credential_version": 1,
        "actions": ["secrets:read"],
        "iss": "envbasis-machine-auth",
        "aud": "envbasis-machine",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "jti": str(uuid.uuid4()),
        "token_use": "machine_access",
    }
    claims.update(overrides)
    return jwt.encode(claims, MACHINE_SECRET, algorithm="HS256")


class UpstreamRecorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response_status = 200
        self.response_headers: dict[str, str] = {"Content-Type": "application/json"}
        self.response_body = b'{"ok":true}'

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.response_status,
            headers=self.response_headers,
            content=self.response_body,
            request=request,
        )


@pytest.fixture
def machine_token() -> str:
    return issue_machine_token()


@pytest.fixture
def recorder() -> UpstreamRecorder:
    return UpstreamRecorder()


@pytest.fixture
def client(recorder: UpstreamRecorder) -> TestClient:
    settings = ProxySettings(
        machine_auth_jwt_secret=MACHINE_SECRET,
        openai_api_key=OPENAI_KEY,
        github_token=GITHUB_TOKEN,
        openai_upstream_url="https://api.openai.com",
        github_upstream_url="https://api.github.com",
        max_request_bytes=4096,
        max_response_bytes=4096,
        control_plane_url=None,
        proxy_service_token=None,
    )
    app = create_app(settings, transport=httpx.MockTransport(recorder.handler))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(machine_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {machine_token}"}

