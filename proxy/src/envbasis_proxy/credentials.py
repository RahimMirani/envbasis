from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
import httpx
from pydantic import SecretStr

from envbasis_proxy.auth import MachinePrincipal
from envbasis_proxy.config import ProxySettings
from envbasis_proxy.errors import proxy_error


MACHINE_PROXY_USE_ACTION = "proxy:use"


@dataclass
class ControlPlaneCredentialResolver:
    client: httpx.AsyncClient
    settings: ProxySettings

    async def resolve(self, *, access_token: str, provider: str) -> str:
        assert self.settings.control_plane_url is not None
        assert self.settings.proxy_service_token is not None
        url = f"{self.settings.control_plane_url}/api/v1/internal/proxy/credentials/resolve"
        try:
            response = await self.client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.proxy_service_token.get_secret_value()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={"machine_access_token": access_token, "provider": provider},
            )
        except httpx.TimeoutException as exc:
            raise proxy_error(
                504,
                "control_plane_timeout",
                "The control plane did not respond before the timeout.",
            ) from exc
        except httpx.HTTPError as exc:
            raise proxy_error(
                502,
                "control_plane_unavailable",
                "The control plane credential lookup failed.",
            ) from exc

        if response.status_code == 401:
            raise proxy_error(401, "invalid_machine_token", "The machine access token is invalid or expired.")
        if response.status_code == 403:
            raise proxy_error(403, "proxy_use_forbidden", "This machine identity cannot use the provider proxy.")
        if response.status_code == 404:
            raise proxy_error(
                503,
                "provider_not_configured",
                "No provider key is stored for this project environment.",
            )
        if response.status_code >= 400:
            raise proxy_error(
                502,
                "control_plane_unavailable",
                "The control plane credential lookup failed.",
            )
        try:
            payload: dict[str, Any] = response.json()
            secret = str(payload["secret"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise proxy_error(
                502,
                "control_plane_unavailable",
                "The control plane returned an invalid credential payload.",
            ) from exc
        if not secret:
            raise proxy_error(
                503,
                "provider_not_configured",
                "No provider key is stored for this project environment.",
            )
        return secret


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    return secret.get_secret_value()


def env_fallback_credential(settings: ProxySettings, provider: str) -> str | None:
    if provider == "openai":
        return _secret_value(settings.openai_api_key)
    if provider == "anthropic":
        return _secret_value(settings.anthropic_api_key)
    if provider == "github":
        return _secret_value(settings.github_token)
    return None


async def resolve_provider_secret(
    request: Request,
    *,
    settings: ProxySettings,
    provider: str,
    principal: MachinePrincipal,
) -> str:
    if settings.uses_control_plane:
        if MACHINE_PROXY_USE_ACTION not in principal.actions:
            raise proxy_error(
                403,
                "proxy_use_forbidden",
                "This machine identity cannot use the provider proxy.",
            )
        resolver: ControlPlaneCredentialResolver = request.app.state.credential_resolver
        return await resolver.resolve(access_token=principal.access_token, provider=provider)

    secret = env_fallback_credential(settings, provider)
    if not secret:
        raise proxy_error(503, "provider_not_configured", f"The {provider} proxy is not configured.")
    return secret
