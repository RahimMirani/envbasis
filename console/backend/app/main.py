import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import Response
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import request_metrics
from app.core.middleware import (
    apply_response_headers,
    assign_request_id,
    build_rate_limit_response,
    build_rate_limiter_unavailable_response,
    rate_limiter,
    RateLimiterUnavailable,
)
from app.db.session import SessionLocal
from app.services.audit import cleanup_old_audit_logs
from app.services.crypto import ensure_secrets_master_key_configured
from app.services.api_idempotency import execute_idempotent_request

logger = logging.getLogger(__name__)

_LOCAL_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"


def _cors_allow_origins(origins: list[str]) -> list[str]:
    aliases: list[str] = []
    for origin in origins:
        if "://localhost" in origin:
            aliases.append(origin.replace("://localhost", "://127.0.0.1", 1))
        elif "://127.0.0.1" in origin:
            aliases.append(origin.replace("://127.0.0.1", "://localhost", 1))
    return list(dict.fromkeys([*origins, *aliases]))


class LoggedCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code >= 400:
            logger.warning(
                "cors_preflight_rejected origin=%s method=%s headers=%s private_network=%s body=%s",
                request_headers.get("origin"),
                request_headers.get("access-control-request-method"),
                request_headers.get("access-control-request-headers"),
                request_headers.get("access-control-request-private-network"),
                bytes(getattr(response, "body", b"")).decode("utf-8", errors="replace"),
            )
        return response


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def operational_middleware(request: Request, call_next):
        started_at = perf_counter()
        request_id = assign_request_id(request)
        status_code = 500
        rate_limit_rule: str | None = None
        try:
            try:
                rate_limit_result = rate_limiter.check(request)
                rate_limit_rule = rate_limit_result.rule_name
            except RateLimiterUnavailable:
                response = build_rate_limiter_unavailable_response(request_id=request_id)
            else:
                if not rate_limit_result.allowed:
                    response = build_rate_limit_response(
                        request_id=request_id,
                        retry_after_seconds=rate_limit_result.retry_after_seconds,
                    )
                else:
                    response = await execute_idempotent_request(request, call_next)
            status_code = response.status_code
            return apply_response_headers(request, response, request_id=request_id)
        finally:
            duration_seconds = perf_counter() - started_at
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", None) or "unmatched"
            request_metrics.observe(
                method=request.method,
                route=route,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            logger.log(
                logging.ERROR if status_code >= 500 else logging.INFO,
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                    "client_ip": request.client.host if request.client else "unknown",
                    "rate_limit_rule": rate_limit_rule,
                },
            )

    if settings.cors_allowed_origins:
        app.add_middleware(
            LoggedCORSMiddleware,
            allow_origins=_cors_allow_origins(settings.cors_allowed_origins),
            allow_origin_regex=_LOCAL_ORIGIN_REGEX,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[
                "Deprecation",
                "Idempotency-Replayed",
                "Link",
                "Sunset",
                "X-API-Version",
                "X-Limit",
                "X-Offset",
                "X-Request-ID",
                "X-Total-Count",
            ],
            allow_private_network=True,
        )
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.on_event("startup")
    def validate_encryption_key_on_startup() -> None:
        ensure_secrets_master_key_configured()

    @app.on_event("startup")
    def cleanup_audit_logs_on_startup() -> None:
        db = SessionLocal()
        try:
            cleanup_old_audit_logs(db, retention_days=settings.audit_log_retention_days)
            db.commit()
        except (OperationalError, ProgrammingError):
            # DB isn't reachable yet or migrations haven't been applied — safe
            # to skip and let the app boot. Any other error is a real bug and
            # should propagate so boot fails loudly.
            db.rollback()
            logger.warning("Startup audit-log cleanup skipped: database not ready.", exc_info=True)
        finally:
            db.close()

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "environment": settings.app_env,
            "status": "ok",
        }

    return app


app = create_app()
