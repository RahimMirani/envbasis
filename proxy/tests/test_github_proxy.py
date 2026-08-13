from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from conftest import GITHUB_TOKEN, UpstreamRecorder


def test_valid_github_read_is_forwarded(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/github/repos/acme/backend/issues?state=open&per_page=10",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert len(recorder.requests) == 1
    upstream = recorder.requests[0]
    assert upstream.url == httpx.URL(
        "https://api.github.com/repos/acme/backend/issues?state=open&per_page=10"
    )
    assert upstream.headers["authorization"] == f"Bearer {GITHUB_TOKEN}"
    assert upstream.headers["x-github-api-version"] == "2022-11-28"


def test_github_merge_is_recognized_and_forwarded(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.put(
        "/github/repos/acme/backend/pulls/42/merge",
        headers=auth_headers,
        json={"merge_method": "squash"},
    )

    assert response.status_code == 200
    assert len(recorder.requests) == 1


def test_all_github_delete_requests_are_blocked(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.delete(
        "/github/repos/acme/backend",
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "operation_blocked"
    assert recorder.requests == []


def test_github_graphql_is_blocked(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/github/graphql",
        headers=auth_headers,
        json={"query": "mutation { deleteRepository(input: {}) { clientMutationId } }"},
    )

    assert response.status_code == 403
    assert recorder.requests == []


def test_github_secret_management_is_blocked(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.put(
        "/github/repos/acme/backend/actions/secrets/PROD_KEY",
        headers=auth_headers,
        json={"encrypted_value": "value", "key_id": "key"},
    )

    assert response.status_code == 403
    assert recorder.requests == []


def test_force_updating_git_reference_is_blocked(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/github/repos/acme/backend/git/refs/heads/main",
        headers=auth_headers,
        json={"sha": "abc123", "force": True},
    )

    assert response.status_code == 403
    assert recorder.requests == []


def test_unknown_github_endpoint_is_default_denied(
    client: TestClient,
    recorder: UpstreamRecorder,
    auth_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/github/repos/acme/backend",
        headers=auth_headers,
        json={"archived": True},
    )

    assert response.status_code == 404
    assert recorder.requests == []

