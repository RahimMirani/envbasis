from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from envbasis_proxy.errors import invalid_request, unsupported_operation
from envbasis_proxy.validation.common import ValidatedRequest, parse_json_body, validate_path


def _require_nonempty_field(body: dict[str, Any], field: str) -> None:
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise invalid_request(f"Anthropic field '{field}' is required.")


def validate_anthropic_request(request: Request, path: str, body: bytes) -> ValidatedRequest:
    normalized = validate_path(path)
    method = request.method.upper()

    operation: str
    json_body: dict[str, Any] | list[Any] | None
    if method == "POST" and normalized == "v1/messages":
        json_body = parse_json_body(request, body, required=True)
        if not isinstance(json_body, dict):
            raise invalid_request("The Anthropic Messages body must be a JSON object.")
        _require_nonempty_field(json_body, "model")
        _require_nonempty_field(json_body, "messages")
        operation = "messages.create"
    elif method == "GET" and normalized == "v1/models":
        if body:
            raise invalid_request("This Anthropic operation does not accept a request body.")
        json_body = None
        operation = "models.list"
    elif method == "GET" and re.fullmatch(r"v1/models/[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", normalized):
        if body:
            raise invalid_request("This Anthropic operation does not accept a request body.")
        json_body = None
        operation = "models.get"
    else:
        raise unsupported_operation("This Anthropic operation is not supported by the proxy.")

    return ValidatedRequest(
        provider="anthropic",
        operation=operation,
        method=method,
        upstream_path=normalized,
        body=body,
        json_body=json_body,
    )
