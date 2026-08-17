from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from hashlib import sha256
import hmac
from ipaddress import ip_address, ip_network
import secrets
from typing import Any
import uuid

import jwt
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.machine_identity import MachineIdentity
from app.models.machine_identity_credential import MachineIdentityCredential


MACHINE_SECRET_READ_ACTION = "secrets:read"
MACHINE_PROXY_USE_ACTION = "proxy:use"


@dataclass(frozen=True)
class IssuedMachineAccessToken:
    access_token: str
    expires_in: int
    expires_at: datetime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_machine_client_id() -> str:
    return f"envb_mi_{secrets.token_urlsafe(settings.machine_auth_client_id_bytes)}"


def generate_machine_client_secret() -> str:
    return f"envb_mis_{secrets.token_urlsafe(settings.machine_auth_client_secret_bytes)}"


def hash_machine_client_secret(client_secret: str) -> str:
    return sha256(client_secret.encode("utf-8")).hexdigest()


def verify_machine_client_secret(*, plaintext: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_machine_client_secret(plaintext), stored_hash)


def normalize_secret_key_patterns(patterns: list[str] | None) -> list[str] | None:
    if patterns is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern:
            raise ValueError("Secret key patterns cannot be empty.")
        if len(pattern) > 128:
            raise ValueError("Secret key patterns cannot exceed 128 characters.")
        if pattern not in seen:
            seen.add(pattern)
            normalized.append(pattern)
    return normalized


def normalize_trusted_cidrs(cidrs: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_cidr in cidrs:
        try:
            cidr = str(ip_network(raw_cidr.strip(), strict=False))
        except ValueError as exc:
            raise ValueError(f"Invalid trusted CIDR: {raw_cidr}.") from exc
        if cidr not in seen:
            seen.add(cidr)
            normalized.append(cidr)
    return normalized


def is_client_ip_allowed(*, client_ip: str | None, trusted_cidrs: list[str]) -> bool:
    if not trusted_cidrs:
        return True
    if not client_ip:
        return False
    try:
        address = ip_address(client_ip)
    except ValueError:
        return False
    return any(address in ip_network(cidr, strict=False) for cidr in trusted_cidrs)


def is_machine_identity_active(identity: MachineIdentity, *, now: datetime | None = None) -> bool:
    effective_now = now or utcnow()
    if identity.revoked_at is not None:
        return False
    if identity.disabled_at is not None:
        return False
    if identity.locked_until is not None and as_utc(identity.locked_until) > effective_now:
        return False
    return True


def validate_access_token_ttl(ttl_seconds: int) -> int:
    if not (
        settings.machine_auth_min_access_token_ttl_seconds
        <= ttl_seconds
        <= settings.machine_auth_max_access_token_ttl_seconds
    ):
        raise ValueError(
            "Machine access-token TTL must be between "
            f"{settings.machine_auth_min_access_token_ttl_seconds} and "
            f"{settings.machine_auth_max_access_token_ttl_seconds} seconds."
        )
    return ttl_seconds


def validate_credential_expiry(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    normalized = as_utc(value)
    if normalized <= utcnow():
        raise ValueError("Machine credential expiry must be in the future.")
    return normalized


def is_machine_credential_active(credential: MachineIdentityCredential, *, now: datetime | None = None) -> bool:
    effective_now = now or utcnow()
    if credential.revoked_at is not None:
        return False
    if credential.expires_at is not None and as_utc(credential.expires_at) <= effective_now:
        return False
    if credential.overlap_expires_at is not None and as_utc(credential.overlap_expires_at) <= effective_now:
        return False
    return True


def issue_machine_access_token(
    identity: MachineIdentity,
    credential: MachineIdentityCredential | None = None,
) -> IssuedMachineAccessToken:
    if not settings.machine_auth_jwt_secret:
        raise RuntimeError("MACHINE_AUTH_JWT_SECRET is not configured.")
    if not is_machine_identity_active(identity):
        raise ValueError("inactive_machine_identity")

    ttl_seconds = validate_access_token_ttl(identity.access_token_ttl_seconds)
    issued_at = utcnow()
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    claims: dict[str, Any] = {
        "sub": str(identity.id),
        "client_id": identity.client_id,
        "project_id": str(identity.project_id) if identity.project_id else None,
        "organization_id": str(identity.organization_id) if identity.organization_id else None,
        "environment_id": str(identity.environment_id) if identity.environment_id else None,
        "credential_version": identity.credential_version,
        "actions": list(identity.allowed_actions),
        "iss": settings.machine_auth_jwt_issuer,
        "aud": settings.machine_auth_jwt_audience,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
        "token_use": "machine_access",
    }
    if credential is not None:
        claims["credential_id"] = str(credential.id)
        claims["credential_version"] = credential.version
        claims["client_id"] = credential.client_id
    elif identity.credential_expires_at is not None and as_utc(identity.credential_expires_at) <= issued_at:
        raise ValueError("inactive_machine_identity")
    access_token = jwt.encode(
        claims,
        settings.machine_auth_jwt_secret,
        algorithm=settings.machine_auth_jwt_algorithm,
    )
    return IssuedMachineAccessToken(
        access_token=access_token,
        expires_in=ttl_seconds,
        expires_at=expires_at,
    )


def decode_machine_access_token(access_token: str) -> dict[str, Any]:
    if not settings.machine_auth_jwt_secret:
        raise RuntimeError("MACHINE_AUTH_JWT_SECRET is not configured.")
    try:
        claims = jwt.decode(
            access_token,
            settings.machine_auth_jwt_secret,
            algorithms=[settings.machine_auth_jwt_algorithm],
            issuer=settings.machine_auth_jwt_issuer,
            audience=settings.machine_auth_jwt_audience,
        )
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise ValueError("invalid_machine_access_token") from exc
    if claims.get("token_use") != "machine_access":
        raise ValueError("invalid_machine_access_token")
    return claims


def resolve_machine_identity_from_access_token(
    db: Session,
    *,
    access_token: str,
) -> MachineIdentity:
    claims = decode_machine_access_token(access_token)
    try:
        identity_id = uuid.UUID(str(claims["sub"]))
        token_version = int(claims["credential_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_machine_access_token") from exc

    identity = db.get(MachineIdentity, identity_id)
    if identity is None or not is_machine_identity_active(identity):
        raise ValueError("invalid_machine_access_token")
    credential_id_value = claims.get("credential_id")
    if credential_id_value is not None:
        try:
            credential_id = uuid.UUID(str(credential_id_value))
        except ValueError as exc:
            raise ValueError("invalid_machine_access_token") from exc
        credential = db.get(MachineIdentityCredential, credential_id)
        if (
            credential is None
            or credential.identity_id != identity.id
            or not is_machine_credential_active(credential)
            or token_version != credential.version
            or claims.get("client_id") != credential.client_id
        ):
            raise ValueError("invalid_machine_access_token")
    else:
        if (
            token_version != identity.credential_version
            or claims.get("client_id") != identity.client_id
            or (
                identity.credential_expires_at is not None
                and as_utc(identity.credential_expires_at) <= utcnow()
            )
        ):
            raise ValueError("invalid_machine_access_token")
    return identity


def secret_key_is_allowed(*, key: str, patterns: list[str] | None) -> bool:
    if patterns is None:
        return True
    return any(fnmatchcase(key, pattern) for pattern in patterns)


def get_machine_identity_by_client_id(
    db: Session,
    *,
    client_id: str,
) -> MachineIdentity | None:
    return db.scalar(
        select(MachineIdentity).where(MachineIdentity.client_id == client_id.strip())
    )


def get_machine_credential_by_client_id(
    db: Session, *, client_id: str
) -> MachineIdentityCredential | None:
    return db.scalar(
        select(MachineIdentityCredential).where(
            MachineIdentityCredential.client_id == client_id.strip()
        )
    )
