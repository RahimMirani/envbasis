from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Literal

import httpx

from envbasis_proxy.auth import MachinePrincipal
from envbasis_proxy.config import ProxySettings
from envbasis_proxy.errors import proxy_error


ProviderName = Literal["openai", "anthropic", "github"]


@dataclass(frozen=True)
class ResolvedCredential:
    credential: str
    credential_version: int
    provider: ProviderName


@dataclass
class _CacheEntry:
    credential: str
    credential_version: int
    expires_at: float


class ProviderCredentialResolver:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, int], _CacheEntry] = {}

    def clear(self) -> None:
        self._cache.clear()

    async def resolve(
        self,
        *,
        client: httpx.AsyncClient,
        settings: ProxySettings,
        principal: MachinePrincipal,
        provider: ProviderName,
        machine_access_token: str,
    ) -> ResolvedCredential:
        if settings.control_plane_url and settings.proxy_service_token:
            return await self._resolve_from_control_plane(
                client=client,
                settings=settings,
                principal=principal,
                provider=provider,
                machine_access_token=machine_access_token,
            )
        return self._resolve_from_env(settings=settings, provider=provider)

    def _resolve_from_env(
        self,
        *,
        settings: ProxySettings,
        provider: ProviderName,
    ) -> ResolvedCredential:
        if provider == "openai":
            secret = settings.openai_api_key
            label = "OpenAI"
        elif provider == "anthropic":
            secret = settings.anthropic_api_key
            label = "Anthropic"
        else:
            secret = settings.github_token
            label = "GitHub"
        if secret is None:
            raise proxy_error(
                503,
                "provider_not_configured",
                f"The {label} proxy is not configured.",
            )
        return ResolvedCredential(
            credential=secret.get_secret_value(),
            credential_version=0,
            provider=provider,
        )

    async def _resolve_from_control_plane(
        self,
        *,
        client: httpx.AsyncClient,
        settings: ProxySettings,
        principal: MachinePrincipal,
        provider: ProviderName,
        machine_access_token: str,
    ) -> ResolvedCredential:
        now = monotonic()
        for entry_key, entry in list(self._cache.items()):
            if entry_key[0] == str(principal.identity_id) and entry_key[1] == provider:
                if entry.expires_at > now:
                    return ResolvedCredential(
                        credential=entry.credential,
                        credential_version=entry.credential_version,
                        provider=provider,
                    )
                self._cache.pop(entry_key, None)

        assert settings.control_plane_url is not None
        assert settings.proxy_service_token is not None
        url = f"{settings.control_plane_url.rstrip('/')}/api/v1/internal/proxy/credentials/resolve"
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.proxy_service_token.get_secret_value()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "machine_access_token": machine_access_token,
                    "provider": provider,
                },
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

        if response.status_code == 404:
            detail = _detail_code(response)
            raise proxy_error(
                503 if detail == "provider_not_configured" else 404,
                detail or "provider_not_configured",
                _detail_message(response)
                or f"No {provider} credential is configured for this environment.",
            )
        if response.status_code in {401, 403}:
            raise proxy_error(
                response.status_code,
                _detail_code(response) or "proxy_credential_forbidden",
                _detail_message(response) or "Provider credential resolve was denied.",
            )
        if response.status_code >= 400:
            raise proxy_error(
                502,
                _detail_code(response) or "control_plane_error",
                _detail_message(response) or "The control plane rejected the credential lookup.",
            )

        try:
            payload = response.json()
            credential = str(payload["credential"])
            credential_version = int(payload.get("credential_version", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise proxy_error(
                502,
                "control_plane_invalid_response",
                "The control plane returned an invalid credential payload.",
            ) from exc

        if not credential:
            raise proxy_error(
                502,
                "control_plane_invalid_response",
                "The control plane returned an empty credential.",
            )

        versioned_key = (str(principal.identity_id), provider, credential_version)
        self._cache[versioned_key] = _CacheEntry(
            credential=credential,
            credential_version=credential_version,
            expires_at=now + settings.credential_cache_ttl_seconds,
        )
        for entry_key in list(self._cache):
            if (
                entry_key[0] == str(principal.identity_id)
                and entry_key[1] == provider
                and entry_key != versioned_key
            ):
                self._cache.pop(entry_key, None)

        return ResolvedCredential(
            credential=credential,
            credential_version=credential_version,
            provider=provider,
        )


def _detail_code(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    if isinstance(detail, dict):
        code = detail.get("code")
        return str(code) if code else None
    return None


def _detail_message(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    if isinstance(detail, dict):
        message = detail.get("message")
        return str(message) if message else None
    if isinstance(detail, str):
        return detail
    return None


credential_resolver = ProviderCredentialResolver()
