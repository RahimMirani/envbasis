from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError

from envbasis_proxy.config import ProxySettings


@dataclass(frozen=True)
class MachinePrincipal:
    identity_id: uuid.UUID
    client_id: str
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    token_id: uuid.UUID


def _optional_uuid(claims: dict[str, Any], key: str) -> uuid.UUID | None:
    value = claims.get(key)
    return uuid.UUID(str(value)) if value else None


def extract_machine_access_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, bearer_token = authorization.partition(" ")
    if scheme.lower() == "bearer" and bearer_token.strip():
        return bearer_token.strip()

    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return api_key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required", "message": "A machine access token is required."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_machine_token(access_token: str, settings: ProxySettings) -> MachinePrincipal:
    try:
        claims = jwt.decode(
            access_token,
            settings.machine_auth_jwt_secret.get_secret_value(),
            algorithms=[settings.machine_auth_jwt_algorithm],
            issuer=settings.machine_auth_jwt_issuer,
            audience=settings.machine_auth_jwt_audience,
            options={"require": ["sub", "client_id", "exp", "iat", "nbf", "jti", "token_use"]},
        )
        if claims.get("token_use") != "machine_access":
            raise ValueError("wrong token use")
        identity_id = uuid.UUID(str(claims["sub"]))
        token_id = uuid.UUID(str(claims["jti"]))
        client_id = str(claims["client_id"]).strip()
        if not client_id:
            raise ValueError("missing client id")
        project_id = _optional_uuid(claims, "project_id")
        organization_id = _optional_uuid(claims, "organization_id")
        environment_id = _optional_uuid(claims, "environment_id")
        if (project_id is None) == (organization_id is None):
            raise ValueError("invalid machine scope")
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_machine_token", "message": "The machine access token is invalid or expired."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return MachinePrincipal(
        identity_id=identity_id,
        client_id=client_id,
        project_id=project_id,
        organization_id=organization_id,
        environment_id=environment_id,
        token_id=token_id,
    )


def authenticate_machine_request(request: Request, settings: ProxySettings) -> MachinePrincipal:
    return authenticate_machine_token(extract_machine_access_token(request), settings)
