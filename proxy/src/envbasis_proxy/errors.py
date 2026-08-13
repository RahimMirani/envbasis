from __future__ import annotations

from fastapi import HTTPException, status


def proxy_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def invalid_request(message: str) -> HTTPException:
    return proxy_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_request", message)


def operation_blocked(message: str) -> HTTPException:
    return proxy_error(status.HTTP_403_FORBIDDEN, "operation_blocked", message)


def unsupported_operation(message: str) -> HTTPException:
    return proxy_error(status.HTTP_404_NOT_FOUND, "unsupported_operation", message)

