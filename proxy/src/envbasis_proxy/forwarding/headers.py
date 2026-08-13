from __future__ import annotations

from collections.abc import Mapping


REQUEST_HEADER_ALLOWLIST = {
    "accept",
    "accept-encoding",
    "content-type",
    "idempotency-key",
    "if-match",
    "if-modified-since",
    "if-none-match",
    "openai-beta",
    "range",
    "user-agent",
    "x-github-api-version",
}

RESPONSE_HEADER_ALLOWLIST = {
    "cache-control",
    "content-disposition",
    "content-type",
    "etag",
    "last-modified",
    "link",
    "openai-processing-ms",
    "retry-after",
    "x-accepted-github-permissions",
    "x-github-api-version-selected",
    "x-github-media-type",
    "x-github-request-id",
    "x-oauth-scopes",
    "x-request-id",
}


def build_upstream_headers(
    incoming: Mapping[str, str],
    *,
    provider: str,
    credential: str,
) -> dict[str, str]:
    headers = {
        name.lower(): value
        for name, value in incoming.items()
        if name.lower() in REQUEST_HEADER_ALLOWLIST
    }
    headers["authorization"] = f"Bearer {credential}"
    if provider == "github":
        headers.setdefault("accept", "application/vnd.github+json")
        headers.setdefault("x-github-api-version", "2022-11-28")
    else:
        headers.setdefault("accept", "application/json")
    return headers


def build_downstream_headers(incoming: Mapping[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in incoming.items():
        lowered = name.lower()
        if lowered in RESPONSE_HEADER_ALLOWLIST or lowered.startswith("x-ratelimit-"):
            headers[name] = value
    return headers
