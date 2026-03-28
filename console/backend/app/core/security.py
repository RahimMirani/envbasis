from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
import uuid

import jwt
from jwt import InvalidTokenError, PyJWKClient

from app.core.config import settings

ALLOWED_JWT_ALGORITHMS = ("HS256", "ES256", "RS256")
ASYMMETRIC_JWT_ALGORITHMS = ("ES256", "RS256")


@dataclass(frozen=True)
class AuthIdentity:
    user_id: uuid.UUID
    email: str
    claims: dict[str, Any]


def build_auth_identity(claims: dict[str, Any]) -> AuthIdentity:
    subject = claims.get("sub")
    email = claims.get("email")
    if not subject:
        raise ValueError("Token is missing the subject claim.")
    if not email:
        raise ValueError("Token is missing the email claim.")

    return AuthIdentity(
        user_id=uuid.UUID(str(subject)),
        email=str(email).strip().lower(),
        claims=claims,
    )


@lru_cache
def get_supabase_jwks_client() -> PyJWKClient:
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is required for asymmetric JWT verification.")

    jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True)


def _decode_supabase_access_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg")
    if algorithm not in ALLOWED_JWT_ALGORITHMS:
        raise ValueError("Invalid access token.")

    decode_kwargs: dict[str, Any] = {
        "algorithms": [algorithm],
    }
    if settings.supabase_jwt_audience:
        decode_kwargs["audience"] = settings.supabase_jwt_audience
    else:
        decode_kwargs["options"] = {"verify_aud": False}

    if algorithm in ASYMMETRIC_JWT_ALGORITHMS:
        signing_key = get_supabase_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, **decode_kwargs)
    if not settings.supabase_jwt_secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is required for symmetric JWT verification.")

    return jwt.decode(token, settings.supabase_jwt_secret, **decode_kwargs)


def _decode_cli_access_token(token: str) -> dict[str, Any]:
    if not settings.cli_auth_jwt_secret:
        raise RuntimeError("CLI_AUTH_JWT_SECRET is required for CLI JWT verification.")
    if settings.cli_auth_jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
        raise RuntimeError("CLI_AUTH_JWT_ALGORITHM is invalid.")

    decode_kwargs: dict[str, Any] = {"algorithms": [settings.cli_auth_jwt_algorithm]}
    if settings.cli_auth_jwt_audience:
        decode_kwargs["audience"] = settings.cli_auth_jwt_audience
    else:
        decode_kwargs["options"] = {"verify_aud": False}
    if settings.cli_auth_jwt_issuer:
        decode_kwargs["issuer"] = settings.cli_auth_jwt_issuer

    claims = jwt.decode(token, settings.cli_auth_jwt_secret, **decode_kwargs)
    if claims.get("token_use") != "access":
        raise ValueError("Invalid access token.")

    return claims


def decode_access_token(token: str) -> dict[str, Any]:
    decoders_attempted = 0

    if settings.supabase_jwt_secret or settings.supabase_url:
        decoders_attempted += 1
        try:
            return _decode_supabase_access_token(token)
        except (InvalidTokenError, RuntimeError, ValueError, TypeError):
            pass

    if settings.cli_auth_jwt_secret:
        decoders_attempted += 1
        try:
            return _decode_cli_access_token(token)
        except (InvalidTokenError, RuntimeError, ValueError, TypeError):
            pass

    if decoders_attempted == 0:
        raise RuntimeError("No access token decoder is configured.")

    raise ValueError("Invalid access token.")
