"""Drop this file into your agent. Standard library only.

You set machine credentials. This module mints the short-lived JWT and
refreshes it before it expires. OpenAI/Anthropic keep reading env vars.

    export ENVBASIS_API_URL=http://127.0.0.1:8000/api/v1
    export ENVBASIS_PROXY_URL=http://localhost:8080
    export ENVBASIS_CLIENT_ID=envb_mi_...
    export ENVBASIS_CLIENT_SECRET=envb_mis_...

    import envbasis_session
    envbasis_session.configure()

    from openai import OpenAI
    client = OpenAI()
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EnvBasisError(RuntimeError):
    pass


class EnvBasisSession:
    def __init__(
        self,
        *,
        api_url: str,
        client_id: str,
        client_secret: str,
        proxy_url: str = "http://localhost:8080",
        refresh_margin_seconds: float = 60.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.proxy_url = proxy_url.rstrip("/")
        self.refresh_margin_seconds = refresh_margin_seconds
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_env(cls) -> "EnvBasisSession":
        api_url = os.environ.get("ENVBASIS_API_URL", "").strip()
        client_id = os.environ.get("ENVBASIS_CLIENT_ID", "").strip()
        client_secret = os.environ.get("ENVBASIS_CLIENT_SECRET", "").strip()
        proxy_url = os.environ.get("ENVBASIS_PROXY_URL", "http://localhost:8080").strip()
        missing = [
            name
            for name, value in (
                ("ENVBASIS_API_URL", api_url),
                ("ENVBASIS_CLIENT_ID", client_id),
                ("ENVBASIS_CLIENT_SECRET", client_secret),
            )
            if not value
        ]
        if missing:
            raise EnvBasisError("Set " + ", ".join(missing) + ".")
        return cls(
            api_url=api_url,
            client_id=client_id,
            client_secret=client_secret,
            proxy_url=proxy_url,
        )

    def __str__(self) -> str:
        return self.token()

    @property
    def openai_base_url(self) -> str:
        return f"{self.proxy_url}/openai/v1"

    @property
    def anthropic_base_url(self) -> str:
        return f"{self.proxy_url}/anthropic"

    def token(self) -> str:
        with self._lock:
            still_fresh = self._token and time.time() < self._expires_at - self.refresh_margin_seconds
            if still_fresh:
                return self._token
        self.refresh()
        with self._lock:
            return self._token

    def refresh(self) -> str:
        payload = json.dumps(
            {"client_id": self.client_id, "client_secret": self.client_secret}
        ).encode("utf-8")
        request = Request(
            f"{self.api_url}/machine-identities/token",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                body: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EnvBasisError(f"Token exchange failed ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise EnvBasisError(f"Token exchange failed: {exc.reason}") from exc

        access_token = str(body.get("access_token") or "").strip()
        if not access_token:
            raise EnvBasisError("Token exchange returned no access_token.")
        expires_in = max(int(body.get("expires_in") or 3600), 1)
        expires_at = _expires_at_timestamp(body.get("expires_at"), expires_in)

        with self._lock:
            self._token = access_token
            self._expires_at = expires_at
        _publish_env(self)
        return access_token

    def start(self) -> "EnvBasisSession":
        self.refresh()
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._refresh_loop,
                name="envbasis-token-refresh",
                daemon=True,
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                wait_for = max(self._expires_at - time.time() - self.refresh_margin_seconds, 5.0)
            if self._stop.wait(wait_for):
                return
            try:
                self.refresh()
            except EnvBasisError:
                if self._stop.wait(15.0):
                    return


def _expires_at_timestamp(raw_expires_at: object, expires_in: int) -> float:
    if isinstance(raw_expires_at, str) and raw_expires_at:
        try:
            parsed = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return time.time() + expires_in


def _publish_env(session: EnvBasisSession) -> None:
    os.environ["ENVBASIS_TOKEN"] = session._token
    os.environ["OPENAI_API_KEY"] = session._token
    os.environ["OPENAI_BASE_URL"] = session.openai_base_url
    os.environ["ANTHROPIC_API_KEY"] = session._token
    os.environ["ANTHROPIC_BASE_URL"] = session.anthropic_base_url
    os.environ.setdefault("GITHUB_TOKEN", session._token)


_session: EnvBasisSession | None = None
api_key: EnvBasisSession | None = None
openai_base_url: str | None = None
anthropic_base_url: str | None = None


def configure() -> EnvBasisSession:
    """Mint a JWT from machine credentials and keep refreshing it."""
    global _session, api_key, openai_base_url, anthropic_base_url
    _session = EnvBasisSession.from_env().start()
    api_key = _session
    openai_base_url = _session.openai_base_url
    anthropic_base_url = _session.anthropic_base_url
    return _session
