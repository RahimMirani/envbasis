from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import request_metrics
from app.core.middleware import rate_limiter
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "environment": settings.app_env,
        "status": "ok",
    }


@router.get("/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness(
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    checks = {"database": False, "rate_limiter": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    checks["rate_limiter"] = rate_limiter.ping()

    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": checks}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        request_metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
