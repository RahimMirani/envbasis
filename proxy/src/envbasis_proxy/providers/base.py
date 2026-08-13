from __future__ import annotations

from dataclasses import dataclass

from envbasis_proxy.validation.common import ValidatedRequest


@dataclass(frozen=True)
class ProviderRequest:
    validated: ValidatedRequest
    upstream_url: str
    credential: str

