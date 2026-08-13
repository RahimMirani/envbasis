from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from fastapi import Request, status

from envbasis_proxy.errors import invalid_request, proxy_error


SAFE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")


@dataclass(frozen=True)
class ValidatedRequest:
    provider: str
    operation: str
    method: str
    upstream_path: str
    body: bytes
    json_body: dict[str, Any] | list[Any] | None


def validate_path(path: str) -> str:
    normalized = path.strip("/")
    if not normalized or not SAFE_PATH_PATTERN.fullmatch(normalized):
        raise invalid_request("The provider path is malformed.")
    if any(segment in {"", ".", ".."} for segment in normalized.split("/")):
        raise invalid_request("The provider path contains an invalid segment.")
    return normalized


async def read_request_body(request: Request, *, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise invalid_request("Content-Length must be an integer.") from exc
        if declared_length < 0 or declared_length > max_bytes:
            raise proxy_error(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "request_too_large",
                f"The request body cannot exceed {max_bytes} bytes.",
            )

    body = await request.body()
    if len(body) > max_bytes:
        raise proxy_error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "request_too_large",
            f"The request body cannot exceed {max_bytes} bytes.",
        )
    return body


def parse_json_body(request: Request, body: bytes, *, required: bool) -> dict[str, Any] | list[Any] | None:
    if not body:
        if required:
            raise invalid_request("A JSON request body is required.")
        return None

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/json", "application/vnd.github+json"} and not content_type.endswith("+json"):
        raise invalid_request("The request body must use a JSON content type.")
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise invalid_request("The request body is not valid JSON.") from exc
    if not isinstance(parsed, (dict, list)):
        raise invalid_request("The JSON request body must be an object or array.")
    return parsed
