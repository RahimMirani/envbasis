from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.provider_credential import (
    ProxyCredentialResolveRequest,
    ProxyCredentialResolveResponse,
)
from app.services.machine_identities import (
    MACHINE_PROXY_USE_ACTION,
    resolve_machine_identity_from_access_token,
)
from app.services.provider_credentials import (
    decrypt_provider_credential,
    get_provider_credential,
)

router = APIRouter(prefix="/internal/proxy")


def _require_proxy_service_token(authorization: str | None) -> None:
    expected = settings.proxy_service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proxy credential resolve is not configured.",
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Proxy service authentication is required.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid proxy service token.",
        )
    try:
        token_matches = hmac.compare_digest(token, expected)
    except ValueError:
        token_matches = False
    if not token_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid proxy service token.",
        )


@router.post("/credentials/resolve", response_model=ProxyCredentialResolveResponse)
def resolve_proxy_credential(
    payload: ProxyCredentialResolveRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> ProxyCredentialResolveResponse:
    _require_proxy_service_token(authorization)
    try:
        identity = resolve_machine_identity_from_access_token(
            db,
            access_token=payload.machine_access_token,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The machine access token is invalid or expired.",
        ) from exc

    if MACHINE_PROXY_USE_ACTION not in identity.allowed_actions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This machine identity cannot use the provider proxy.",
        )
    if identity.organization_id is not None or identity.project_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization-scoped identities cannot use the provider proxy.",
        )
    if identity.environment_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This machine identity is not bound to an environment.",
        )

    row = get_provider_credential(
        db,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        provider=payload.provider,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No provider credential is configured for this environment.",
        )
    secret = decrypt_provider_credential(db, row)
    return ProxyCredentialResolveResponse(provider=payload.provider, secret=secret)
