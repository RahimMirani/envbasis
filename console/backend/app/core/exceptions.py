from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(
    request: Request,
    *,
    status_code: int,
    detail,
    error: str,
    headers: dict[str, str] | None = None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    content: dict[str, object] = {
        "detail": detail,
        "error": error,
        "request_id": _request_id(request),
    }
    if errors is not None:
        content["errors"] = errors
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        return _response(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error="http_error",
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": [str(part) for part in error.get("loc", ())],
                "message": error.get("msg", "Invalid value."),
                "type": error.get("type", "validation_error"),
            }
            for error in exc.errors()
        ]
        return _response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request validation failed.",
            error="validation_error",
            errors=safe_errors,
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning(
            "database_integrity_error",
            extra={"request_id": _request_id(request)},
        )
        return _response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            detail="The request conflicts with existing data.",
            error="conflict",
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "database_error",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"request_id": _request_id(request)},
        )
        return _response(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The data service is temporarily unavailable.",
            error="service_unavailable",
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_application_error",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"request_id": _request_id(request)},
        )
        return _response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
            error="internal_error",
        )
