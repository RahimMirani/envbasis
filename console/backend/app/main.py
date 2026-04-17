import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api.router import api_router
from app.core.config import settings
from app.core.middleware import (
    apply_response_headers,
    assign_request_id,
    build_rate_limit_response,
    rate_limiter,
)
from app.db.session import SessionLocal
from app.services.audit import cleanup_old_audit_logs

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    @app.middleware("http")
    async def operational_middleware(request: Request, call_next):
        request_id = assign_request_id(request)
        rate_limit_result = rate_limiter.check(request)
        if not rate_limit_result.allowed:
            response = build_rate_limit_response(
                request_id=request_id,
                retry_after_seconds=rate_limit_result.retry_after_seconds,
            )
            return apply_response_headers(request, response, request_id=request_id)

        response = await call_next(request)
        return apply_response_headers(request, response, request_id=request_id)

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.include_router(api_router, prefix=settings.api_v1_prefix)

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
