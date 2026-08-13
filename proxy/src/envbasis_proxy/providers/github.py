from __future__ import annotations

from envbasis_proxy.config import ProxySettings
from envbasis_proxy.errors import proxy_error
from envbasis_proxy.providers.base import ProviderRequest
from envbasis_proxy.validation.common import ValidatedRequest


def build_github_provider_request(
    validated: ValidatedRequest,
    settings: ProxySettings,
) -> ProviderRequest:
    if settings.github_token is None:
        raise proxy_error(503, "provider_not_configured", "The GitHub proxy is not configured.")
    return ProviderRequest(
        validated=validated,
        upstream_url=f"{settings.github_upstream_url}/{validated.upstream_path}",
        credential=settings.github_token.get_secret_value(),
    )

