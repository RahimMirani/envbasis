from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
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
    utcnow,
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
            detail={
                "code": "proxy_service_unconfigured",
                "message": "Proxy credential resolve is not configured.",
            },
        )
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "proxy_authentication_required",
                "message": "A proxy service token is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_proxy_service_token",
                "message": "The proxy service token is invalid.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/credentials/resolve",
    response_model=ProxyCredentialResolveResponse,
)
def resolve_proxy_credential(
    payload: ProxyCredentialResolveRequest,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> ProxyCredentialResolveResponse:
    _require_proxy_service_token(authorization)
    try:
        identity = resolve_machine_identity_from_access_token(
            db,
            access_token=payload.machine_access_token,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_machine_token",
                "message": "The machine access token is invalid or expired.",
            },
        ) from exc

    if MACHINE_PROXY_USE_ACTION not in (identity.allowed_actions or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "proxy_use_forbidden",
                "message": "This machine identity is not allowed to use the provider proxy.",
            },
        )
    if identity.project_id is None or identity.environment_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "proxy_scope_unsupported",
                "message": "Only project-scoped machine identities with an environment can use the provider proxy.",
            },
        )

    credential = get_provider_credential(
        db,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        provider=payload.provider,
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "provider_not_configured",
                "message": f"No {payload.provider} credential is configured for this environment.",
            },
        )

    plaintext = decrypt_provider_credential(db, credential=credential)
    identity.last_used_at = utcnow()
    db.commit()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return ProxyCredentialResolveResponse(
        provider=payload.provider,
        credential=plaintext,
        project_id=identity.project_id,
        environment_id=identity.environment_id,
        machine_identity_id=identity.id,
        credential_version=identity.credential_version,
    )
