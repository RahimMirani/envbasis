from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from envbasis_proxy.errors import invalid_request, operation_blocked, unsupported_operation
from envbasis_proxy.validation.common import ValidatedRequest, parse_json_body, validate_path


OPENAI_ID = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}"


def _require_nonempty_field(body: dict[str, Any], field: str) -> None:
    value = body.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise invalid_request(f"OpenAI field '{field}' is required.")


def validate_openai_request(request: Request, path: str, body: bytes) -> ValidatedRequest:
    normalized = validate_path(path)
    method = request.method.upper()

    blocked_prefixes = (
        "v1/organization/",
        "v1/projects/",
        "v1/admin/",
        "v1/api_keys",
    )
    if normalized == "v1/organization" or normalized.startswith(blocked_prefixes):
        raise operation_blocked("OpenAI administration and API-key operations are disabled.")

    operation: str
    json_body: dict[str, Any] | list[Any] | None
    if method == "POST" and normalized == "v1/responses":
        json_body = parse_json_body(request, body, required=True)
        if not isinstance(json_body, dict):
            raise invalid_request("The OpenAI Responses body must be a JSON object.")
        _require_nonempty_field(json_body, "model")
        operation = "responses.create"
    elif method == "GET" and re.fullmatch(rf"v1/responses/{OPENAI_ID}", normalized):
        if body:
            raise invalid_request("This OpenAI operation does not accept a request body.")
        json_body = None
        operation = "responses.get"
    elif method == "POST" and re.fullmatch(rf"v1/responses/{OPENAI_ID}/cancel", normalized):
        json_body = parse_json_body(request, body, required=False)
        if json_body is not None and not isinstance(json_body, dict):
            raise invalid_request("The OpenAI cancel body must be a JSON object.")
        operation = "responses.cancel"
    elif method == "GET" and normalized == "v1/models":
        if body:
            raise invalid_request("This OpenAI operation does not accept a request body.")
        json_body = None
        operation = "models.list"
    elif method == "POST" and normalized == "v1/chat/completions":
        json_body = parse_json_body(request, body, required=True)
        if not isinstance(json_body, dict):
            raise invalid_request("The OpenAI Chat Completions body must be a JSON object.")
        _require_nonempty_field(json_body, "model")
        _require_nonempty_field(json_body, "messages")
        operation = "chat.completions.create"
    elif method == "POST" and normalized == "v1/embeddings":
        json_body = parse_json_body(request, body, required=True)
        if not isinstance(json_body, dict):
            raise invalid_request("The OpenAI embeddings body must be a JSON object.")
        _require_nonempty_field(json_body, "model")
        _require_nonempty_field(json_body, "input")
        operation = "embeddings.create"
    else:
        raise unsupported_operation("This OpenAI operation is not supported by the proxy.")

    return ValidatedRequest(
        provider="openai",
        operation=operation,
        method=method,
        upstream_path=normalized,
        body=body,
        json_body=json_body,
    )

