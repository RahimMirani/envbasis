from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError

import envbasis_session


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_configure_sets_openai_env(monkeypatch) -> None:
    monkeypatch.setenv("ENVBASIS_API_URL", "http://127.0.0.1:8000/api/v1")
    monkeypatch.setenv("ENVBASIS_CLIENT_ID", "envb_mi_test")
    monkeypatch.setenv("ENVBASIS_CLIENT_SECRET", "envb_mis_test")
    monkeypatch.setenv("ENVBASIS_PROXY_URL", "http://localhost:8080")

    def fake_urlopen(request, timeout=15):
        assert request.full_url.endswith("/machine-identities/token")
        return _FakeResponse({"access_token": "jwt-one", "expires_in": 3600})

    monkeypatch.setattr(envbasis_session, "urlopen", fake_urlopen)
    session = envbasis_session.EnvBasisSession.from_env()
    session.refresh()
    session.stop()

    assert str(session) == "jwt-one"
    assert envbasis_session.os.environ["OPENAI_API_KEY"] == "jwt-one"
    assert envbasis_session.os.environ["OPENAI_BASE_URL"] == "http://localhost:8080/openai/v1"
    assert envbasis_session.os.environ["ANTHROPIC_BASE_URL"] == "http://localhost:8080/anthropic"


def test_refresh_raises_on_http_error(monkeypatch) -> None:
    session = envbasis_session.EnvBasisSession(
        api_url="http://127.0.0.1:8000/api/v1",
        client_id="id",
        client_secret="secret",
    )

    def fake_urlopen(request, timeout=15):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"detail":"nope"}'),
        )

    monkeypatch.setattr(envbasis_session, "urlopen", fake_urlopen)
    try:
        session.refresh()
        raise AssertionError("expected EnvBasisError")
    except envbasis_session.EnvBasisError as exc:
        assert "401" in str(exc)
