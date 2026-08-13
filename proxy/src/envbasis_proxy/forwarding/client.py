from __future__ import annotations

from collections.abc import AsyncIterator
import logging

from fastapi import Request
from fastapi.responses import StreamingResponse
import httpx

from envbasis_proxy.auth import MachinePrincipal
from envbasis_proxy.config import ProxySettings
from envbasis_proxy.errors import proxy_error
from envbasis_proxy.forwarding.headers import build_downstream_headers, build_upstream_headers
from envbasis_proxy.forwarding.leakage import redact_stream
from envbasis_proxy.providers.base import ProviderRequest


logger = logging.getLogger("envbasis.proxy")


async def _close_after_stream(
    response: httpx.Response,
    *,
    credential: str,
    max_bytes: int,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in redact_stream(
            response.aiter_bytes(),
            secrets=(credential.encode("utf-8"),),
            max_bytes=max_bytes,
        ):
            yield chunk
    finally:
        await response.aclose()


async def forward_request(
    request: Request,
    *,
    provider_request: ProviderRequest,
    principal: MachinePrincipal,
    settings: ProxySettings,
) -> StreamingResponse:
    client: httpx.AsyncClient = request.app.state.http_client
    query = request.url.query
    upstream_url = provider_request.upstream_url
    if query:
        upstream_url = f"{upstream_url}?{query}"
    headers = build_upstream_headers(
        request.headers,
        provider=provider_request.validated.provider,
        credential=provider_request.credential,
    )
    upstream_request = client.build_request(
        provider_request.validated.method,
        upstream_url,
        headers=headers,
        content=provider_request.validated.body or None,
    )

    try:
        response = await client.send(upstream_request, stream=True, follow_redirects=False)
    except httpx.TimeoutException as exc:
        raise proxy_error(504, "upstream_timeout", "The provider did not respond before the timeout.") from exc
    except httpx.HTTPError as exc:
        raise proxy_error(502, "upstream_unavailable", "The provider request failed.") from exc

    if 300 <= response.status_code < 400:
        await response.aclose()
        raise proxy_error(502, "upstream_redirect_blocked", "Provider redirects are not followed by the proxy.")

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > settings.max_response_bytes
        except ValueError:
            too_large = True
        if too_large:
            await response.aclose()
            raise proxy_error(502, "upstream_response_too_large", "The provider response exceeds the proxy limit.")

    logger.info(
        "provider request",
        extra={
            "provider": provider_request.validated.provider,
            "operation": provider_request.validated.operation,
            "machine_identity_id": str(principal.identity_id),
            "project_id": str(principal.project_id) if principal.project_id else None,
            "environment_id": str(principal.environment_id) if principal.environment_id else None,
            "upstream_status": response.status_code,
        },
    )
    downstream_headers = build_downstream_headers(response.headers)
    return StreamingResponse(
        _close_after_stream(
            response,
            credential=provider_request.credential,
            max_bytes=settings.max_response_bytes,
        ),
        status_code=response.status_code,
        headers=downstream_headers,
    )

