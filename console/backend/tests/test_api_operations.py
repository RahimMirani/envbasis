from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import pytest
from cryptography.fernet import Fernet

import app.api.routes.health as health_routes
import app.services.api_idempotency as idempotency_service
from app.api.pagination import paginate_items
from app.core.config import Settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import JsonLogFormatter
from app.core.metrics import RequestMetrics
from app.core.middleware import (
    RateLimiterUnavailable,
    RedisRateLimiter,
    apply_response_headers,
    assign_request_id,
)
from app.models.api_idempotency_record import ApiIdempotencyRecord
from app.services.api_idempotency import (
    claim_idempotency_key,
    complete_idempotency_record,
    is_sensitive_create_request,
)


def _request(
    path: str = "/api/v1/projects",
    *,
    method: str = "GET",
    authorization: str | None = None,
    request_id: str | None = None,
    body: bytes = b"",
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    if request_id:
        headers.append((b"x-request-id", request_id.encode("utf-8")))
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"token=must-not-be-logged",
            "headers": headers,
            "client": ("203.0.113.25", 50000),
            "server": ("api.example.test", 443),
        },
        receive=receive,
    )


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []
        self.available = True

    def eval(self, _script, _key_count, key, window_seconds):
        if not self.available:
            raise ConnectionError("redis unavailable")
        self.keys.append(key)
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], int(window_seconds)]

    def ping(self):
        if not self.available:
            raise ConnectionError("redis unavailable")
        return True


def test_redis_rate_limit_is_shared_and_uses_anonymous_keys(monkeypatch) -> None:
    import app.core.middleware as middleware

    monkeypatch.setattr(middleware.settings, "rate_limit_general_requests", 2)
    monkeypatch.setattr(middleware.settings, "rate_limit_general_window_seconds", 60)
    redis = FakeRedis()
    first_api_instance = RedisRateLimiter(redis, key_prefix="test")
    second_api_instance = RedisRateLimiter(redis, key_prefix="test")
    request = _request(authorization="Bearer super-secret-access-token")

    assert first_api_instance.check(request).allowed is True
    assert second_api_instance.check(request).allowed is True
    blocked = first_api_instance.check(request)

    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 60
    assert blocked.rule_name == "general"
    assert len(set(redis.keys)) == 1
    assert "super-secret-access-token" not in redis.keys[0]

    cli_auth = second_api_instance.check(
        _request("/api/v1/cli/auth/start", authorization="Bearer super-secret-access-token")
    )
    assert cli_auth.rule_name == "auth"
    assert len(set(redis.keys)) == 2


def test_redis_rate_limiter_fails_closed_when_shared_store_is_unavailable() -> None:
    redis = FakeRedis()
    redis.available = False
    limiter = RedisRateLimiter(redis)

    try:
        limiter.check(_request())
    except RateLimiterUnavailable as exc:
        assert str(exc) == "Shared rate limiter is unavailable."
    else:  # pragma: no cover - assertion branch
        raise AssertionError("Redis outage must not silently disable request limits.")
    assert limiter.check(_request("/api/v1/live")).allowed is True
    assert limiter.ping() is False


def test_request_ids_are_validated_before_structured_logging() -> None:
    assert assign_request_id(_request(request_id="client-request_123")) == "client-request_123"
    generated = assign_request_id(_request(request_id="bad\nlog-entry"))
    assert generated != "bad\nlog-entry"
    assert len(generated) == 36


def test_json_log_formatter_emits_structured_safe_fields() -> None:
    record = logging.LogRecord(
        name="envbasis.requests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-123"
    record.method = "GET"
    record.path = "/api/v1/projects"
    record.route = "/api/v1/projects"
    record.status_code = 200
    record.duration_ms = 12.5

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "http_request"
    assert payload["request_id"] == "request-123"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.5
    assert "must-not-be-logged" not in json.dumps(payload)


def test_request_metrics_include_latency_and_error_counters() -> None:
    metrics = RequestMetrics()
    metrics.observe(
        method="GET",
        route="/projects/{project_id}",
        status_code=200,
        duration_seconds=0.025,
    )
    metrics.observe(
        method="GET",
        route="/projects/{project_id}",
        status_code=503,
        duration_seconds=0.075,
    )

    output = metrics.render_prometheus()

    assert 'envbasis_http_requests_total{method="GET",route="/projects/{project_id}",status="200"} 1' in output
    assert 'envbasis_http_requests_total{method="GET",route="/projects/{project_id}",status="503"} 1' in output
    assert 'envbasis_http_request_duration_seconds_count{method="GET",route="/projects/{project_id}"} 2' in output
    assert 'envbasis_http_errors_total{method="GET",route="/projects/{project_id}",status="503"} 1' in output


class HealthyDatabase:
    def execute(self, _statement):
        return object()


class UnhealthyDatabase:
    def execute(self, _statement):
        raise RuntimeError("database unavailable")


class HealthLimiter:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    def ping(self) -> bool:
        return self.healthy


def test_health_liveness_readiness_and_metrics_endpoints(monkeypatch) -> None:
    assert health_routes.healthcheck()["status"] == "ok"
    assert health_routes.liveness() == {"status": "ok"}

    monkeypatch.setattr(health_routes, "rate_limiter", HealthLimiter(True))
    ready_response = Response()
    ready = health_routes.readiness(ready_response, HealthyDatabase())
    assert ready == {
        "status": "ready",
        "checks": {"database": True, "rate_limiter": True},
    }
    assert ready_response.status_code == 200

    monkeypatch.setattr(health_routes, "rate_limiter", HealthLimiter(False))
    unavailable_response = Response()
    unavailable = health_routes.readiness(unavailable_response, UnhealthyDatabase())
    assert unavailable["status"] == "not_ready"
    assert unavailable_response.status_code == 503

    metrics_response = health_routes.metrics()
    assert metrics_response.status_code == 200
    assert b"envbasis_http_requests_total" in metrics_response.body


def test_production_configuration_requires_shared_redis() -> None:
    production = {
        "database_url": "postgresql+psycopg://app:password@db.real.supabase.co:5432/postgres",
        "app_env": "production",
        "ENVBASIS_DEBUG": False,
        "supabase_jwt_secret": "production-supabase-secret",
        "secrets_master_key": "production-root-key",
        "cors_allowed_origins": ["https://console.example.test"],
        "cli_auth_jwt_secret": "production-cli-secret",
        "machine_auth_jwt_secret": "production-machine-secret",
    }

    with pytest.raises(ValueError, match="RATE_LIMIT_BACKEND=redis"):
        Settings(**production, rate_limit_backend="memory", _env_file=None)

    configured = Settings(
        **production,
        rate_limit_backend="redis",
        redis_url="rediss://default:password@redis.example.test:6379/0",
        api_idempotency_encryption_key=Fernet.generate_key().decode("utf-8"),
        _env_file=None,
    )
    assert configured.rate_limit_backend == "redis"


def test_debug_setting_uses_namespaced_environment_variable(monkeypatch) -> None:
    database_url = "postgresql+psycopg://app:password@db.real.supabase.co:5432/postgres"
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.delenv("ENVBASIS_DEBUG", raising=False)

    settings_without_namespaced_debug = Settings(database_url=database_url, _env_file=None)

    assert settings_without_namespaced_debug.debug is False

    monkeypatch.setenv("ENVBASIS_DEBUG", "true")
    settings_with_namespaced_debug = Settings(database_url=database_url, _env_file=None)

    assert settings_with_namespaced_debug.debug is True


def test_pagination_preserves_arrays_and_sets_metadata_headers() -> None:
    response = Response()
    page = paginate_items(list(range(10)), limit=3, offset=4, response=response)

    assert page == [4, 5, 6]
    assert response.headers["X-Total-Count"] == "10"
    assert response.headers["X-Limit"] == "3"
    assert response.headers["X-Offset"] == "4"

    with pytest.raises(ValueError, match="between 1 and 200"):
        paginate_items([1, 2], limit=0)


def test_idempotency_replays_encrypted_response_and_rejects_key_reuse(
    session_factory,
) -> None:
    request = _request(
        "/api/v1/projects",
        method="POST",
        authorization="Bearer user-access-token",
    )
    assign_request_id(request)
    assert is_sensitive_create_request(request) is True

    with session_factory() as db:
        first = claim_idempotency_key(
            db,
            request=request,
            key="create-project-123",
            body=b'{"name":"agent"}',
        )
        assert first.record is not None
        record_id = first.record.id
        complete_idempotency_record(
            db,
            record_id=record_id,
            response_status=201,
            response_headers={"Content-Type": "application/json", "Authorization": "never-store"},
            response_body=b'{"plaintext_token":"one-time-secret"}',
        )

    with session_factory() as db:
        stored = db.get(ApiIdempotencyRecord, record_id)
        assert stored is not None
        assert stored.encrypted_response_body is not None
        assert b"one-time-secret" not in stored.encrypted_response_body
        assert stored.response_headers == {"Content-Type": "application/json"}

        replay = claim_idempotency_key(
            db,
            request=request,
            key="create-project-123",
            body=b'{"name":"agent"}',
        )
        assert replay.replay is not None
        assert replay.replay.status_code == 201
        assert replay.replay.body == b'{"plaintext_token":"one-time-secret"}'
        assert replay.replay.headers["Idempotency-Replayed"] == "true"

        conflict = claim_idempotency_key(
            db,
            request=request,
            key="create-project-123",
            body=b'{"name":"different"}',
        )
        assert conflict.error is not None
        assert conflict.error.status_code == 409


def test_idempotency_reports_an_in_flight_duplicate(session_factory) -> None:
    request = _request(
        "/api/v1/projects/project-id/webhooks",
        method="POST",
        authorization="Bearer user-access-token",
    )
    assign_request_id(request)

    with session_factory() as db:
        first = claim_idempotency_key(
            db,
            request=request,
            key="create-webhook-123",
            body=b'{"url":"https://hooks.example.test"}',
        )
        assert first.record is not None
        duplicate = claim_idempotency_key(
            db,
            request=request,
            key="create-webhook-123",
            body=b'{"url":"https://hooks.example.test"}',
        )
        assert duplicate.error is not None
        assert duplicate.error.status_code == 409
        assert duplicate.error.headers["Retry-After"] == "1"


def test_idempotency_middleware_executes_once_and_replays(
    session_factory,
    monkeypatch,
) -> None:
    monkeypatch.setattr(idempotency_service, "SessionLocal", session_factory)
    calls = 0

    async def call_next(_request):
        nonlocal calls
        calls += 1
        return StreamingResponse(
            iter([b'{"client_secret":"shown-once"}']),
            status_code=201,
            media_type="application/json",
        )

    def new_request():
        request = _request(
            "/api/v1/projects/project-id/machine-identities",
            method="POST",
            authorization="Bearer user-access-token",
            body=b'{"name":"production-agent"}',
        )
        request.scope["headers"].append((b"idempotency-key", b"machine-create-123"))
        assign_request_id(request)
        return request

    first = asyncio.run(
        idempotency_service.execute_idempotent_request(new_request(), call_next)
    )
    second = asyncio.run(
        idempotency_service.execute_idempotent_request(new_request(), call_next)
    )

    assert calls == 1
    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"
    assert second.status_code == 201
    assert second.headers["Idempotency-Replayed"] == "true"
    assert first.body == second.body == b'{"client_secret":"shown-once"}'


def test_central_exception_handler_hides_internal_details() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    request = _request()
    assign_request_id(request)

    unexpected_handler = app.exception_handlers[Exception]
    unexpected_response = asyncio.run(
        unexpected_handler(request, RuntimeError("database password is super-secret"))
    )
    unexpected_body = json.loads(unexpected_response.body)
    assert unexpected_response.status_code == 500
    assert unexpected_body["error"] == "internal_error"
    assert unexpected_body["request_id"] == request.state.request_id
    assert "super-secret" not in unexpected_response.body.decode("utf-8")

    http_handler = app.exception_handlers[HTTPException]
    http_response = asyncio.run(
        http_handler(request, HTTPException(status_code=404, detail="Project not found."))
    )
    assert json.loads(http_response.body)["detail"] == "Project not found."


def test_api_version_and_legacy_deprecation_headers() -> None:
    current = apply_response_headers(
        _request("/api/v1/projects"),
        Response(),
        request_id="request-current",
    )
    assert current.headers["X-API-Version"] == "1"
    assert "Deprecation" not in current.headers

    legacy = apply_response_headers(
        _request("/api/v1/projects/project-id/runtime-tokens"),
        Response(),
        request_id="request-legacy",
    )
    assert legacy.headers["Deprecation"] == "true"
    assert "Sunset" in legacy.headers
    assert 'rel="successor-version"' in legacy.headers["Link"]
