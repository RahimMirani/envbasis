from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

from envbasis_proxy.auth import authenticate_machine_request
from envbasis_proxy.config import ProxySettings, get_settings
from envbasis_proxy.forwarding.client import forward_request
from envbasis_proxy.providers.github import build_github_provider_request
from envbasis_proxy.providers.openai import build_openai_provider_request
from envbasis_proxy.validation.common import read_request_body
from envbasis_proxy.validation.github import validate_github_request
from envbasis_proxy.validation.openai import validate_openai_request


logger = logging.getLogger("envbasis.proxy")


def create_app(
    settings: ProxySettings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    effective_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(effective_settings.upstream_timeout_seconds),
            follow_redirects=False,
            transport=transport,
        )
        yield
        await app.state.http_client.aclose()

    app = FastAPI(
        title=effective_settings.app_name,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = effective_settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route(
        "/openai/{provider_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def openai_proxy(request: Request, provider_path: str):
        principal = authenticate_machine_request(request, effective_settings)
        body = await read_request_body(request, max_bytes=effective_settings.max_request_bytes)
        validated = validate_openai_request(request, provider_path, body)
        provider_request = build_openai_provider_request(validated, effective_settings)
        return await forward_request(
            request,
            provider_request=provider_request,
            principal=principal,
            settings=effective_settings,
        )

    @app.api_route(
        "/github/{provider_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def github_proxy(request: Request, provider_path: str):
        principal = authenticate_machine_request(request, effective_settings)
        body = await read_request_body(request, max_bytes=effective_settings.max_request_bytes)
        validated = validate_github_request(request, provider_path, body)
        provider_request = build_github_provider_request(validated, effective_settings)
        return await forward_request(
            request,
            provider_request=provider_request,
            principal=principal,
            settings=effective_settings,
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
        logger.error("proxy stream failed", exc_info=exc)
        return JSONResponse(
            status_code=502,
            content={"detail": {"code": "proxy_stream_failed", "message": "The provider response stream failed."}},
        )

    return app


app = create_app()

