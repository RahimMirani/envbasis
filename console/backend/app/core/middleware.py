from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.runtime_tokens import hash_runtime_token


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    def check(self, request: Request) -> RateLimitResult:
        if request.method == "OPTIONS":
            return RateLimitResult(allowed=True)

        rule = _get_rate_limit_rule(request.url.path)
        subject = _get_rate_limit_subject(request, rule.name)
        now = monotonic()
        key = (rule.name, subject)

        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window[0] >= rule.window_seconds:
                self._windows[key] = (now, 1)
                return RateLimitResult(allowed=True)

            started_at, count = window
            if count >= rule.max_requests:
                retry_after = max(1, int(rule.window_seconds - (now - started_at)))
                return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

            self._windows[key] = (started_at, count + 1)
            return RateLimitResult(allowed=True)


rate_limiter = InMemoryRateLimiter()


def build_rate_limit_response(*, request_id: str, retry_after_seconds: int) -> JSONResponse:
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please retry later.",
            "request_id": request_id,
        },
    )
    response.headers["Retry-After"] = str(retry_after_seconds)
    return response


def apply_response_headers(request: Request, response: Response, *, request_id: str) -> Response:
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    return response


def assign_request_id(request: Request) -> str:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    return request_id


def _get_rate_limit_rule(path: str) -> RateLimitRule:
    if path.startswith(f"{settings.api_v1_prefix}/runtime/secrets"):
        return RateLimitRule(
            name="runtime",
            max_requests=settings.rate_limit_runtime_requests,
            window_seconds=settings.rate_limit_runtime_window_seconds,
        )
    if path.startswith(f"{settings.api_v1_prefix}/auth"):
        return RateLimitRule(
            name="auth",
            max_requests=settings.rate_limit_auth_requests,
            window_seconds=settings.rate_limit_auth_window_seconds,
        )
    if path.endswith("/secrets/push") or path.endswith("/secrets/pull"):
        return RateLimitRule(
            name="secrets",
            max_requests=settings.rate_limit_secret_requests,
            window_seconds=settings.rate_limit_secret_window_seconds,
        )
    return RateLimitRule(
        name="general",
        max_requests=settings.rate_limit_general_requests,
        window_seconds=settings.rate_limit_general_window_seconds,
    )


def _get_rate_limit_subject(request: Request, rule_name: str) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        parts = authorization.split(" ", 1)
        token = parts[1] if len(parts) == 2 else authorization
        if rule_name == "runtime":
            return f"runtime:{hash_runtime_token(token)}"
        return f"auth:{sha256(authorization.encode('utf-8')).hexdigest()}"

    client_host = request.client.host if request.client is not None else "unknown"
    return f"ip:{client_host}"
