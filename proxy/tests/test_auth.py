from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conftest import issue_machine_token


def test_machine_token_is_required(client: TestClient) -> None:
    response = client.get("/github/repos/acme/app")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_expired_machine_token_is_rejected(client: TestClient) -> None:
    expired = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    response = client.get(
        "/github/repos/acme/app",
        headers={"Authorization": f"Bearer {issue_machine_token(exp=expired)}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_machine_token"


def test_non_machine_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/github/repos/acme/app",
        headers={"Authorization": f"Bearer {issue_machine_token(token_use='user_access')}"},
    )

    assert response.status_code == 401

