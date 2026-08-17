from __future__ import annotations

from envbasis_proxy.config import ProxySettings
from envbasis_proxy.providers.base import ProviderRequest
from envbasis_proxy.validation.common import ValidatedRequest


def build_openai_provider_request(
    validated: ValidatedRequest,
    settings: ProxySettings,
    *,
    credential: str,
) -> ProviderRequest:
    return ProviderRequest(
        validated=validated,
        upstream_url=f"{settings.openai_upstream_url}/{validated.upstream_path}",
        credential=credential,
    )
