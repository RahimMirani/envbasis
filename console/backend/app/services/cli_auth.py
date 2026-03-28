from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
import string
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.cli_auth_refresh_token import CliAuthRefreshToken
from app.models.cli_auth_session import CliAuthSession
from app.models.user import User

CLI_AUTH_USER_CODE_ALPHABET = "".join(
    character for character in string.ascii_uppercase + string.digits if character not in {"0", "1", "I", "O"}
)


@dataclass(frozen=True)
class CliTokenPair:
    access_token: str
    refresh_token: str
    refresh_token_id: uuid.UUID
    expires_at: datetime
    expires_in: int


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_cli_auth_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def normalize_user_code(user_code: str) -> str:
    return "".join(character for character in user_code.upper() if character.isalnum())


def generate_device_code() -> str:
    return secrets.token_urlsafe(settings.cli_auth_device_code_bytes)


def generate_refresh_token() -> str:
    return f"envb_crt_{secrets.token_urlsafe(settings.cli_auth_refresh_token_bytes)}"


def generate_user_code() -> str:
    length = 8
    raw_code = "".join(secrets.choice(CLI_AUTH_USER_CODE_ALPHABET) for _ in range(length))
    return f"{raw_code[:4]}-{raw_code[4:]}"


def build_verification_urls(user_code: str) -> tuple[str, str]:
    verification_url = settings.cli_auth_verification_url.strip()
    if not verification_url:
        raise RuntimeError("CLI_AUTH_VERIFICATION_URL must not be empty.")

    parsed_url = urlparse(verification_url)
    query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    query_params["code"] = user_code
    complete_url = urlunparse(parsed_url._replace(query=urlencode(query_params)))
    return verification_url, complete_url


def expire_session_if_needed(
    session: CliAuthSession,
    *,
    now: datetime | None = None,
) -> bool:
    effective_now = now or utcnow()
    if (
        session.status in {"pending", "approved"}
        and session.expires_at <= effective_now
    ):
        session.status = "expired"
        return True

    return False


def _encode_cli_access_token(claims: dict[str, object]) -> str:
    if not settings.cli_auth_jwt_secret:
        raise RuntimeError("CLI_AUTH_JWT_SECRET is not configured.")
    return jwt.encode(
        claims,
        settings.cli_auth_jwt_secret,
        algorithm=settings.cli_auth_jwt_algorithm,
    )


def issue_cli_token_pair(
    db: Session,
    *,
    user: User,
    cli_auth_session: CliAuthSession | None = None,
) -> CliTokenPair:
    issued_at = utcnow()
    access_expires_in = settings.cli_auth_access_token_ttl_seconds
    refresh_expires_in = settings.cli_auth_refresh_token_ttl_seconds
    access_expires_at = issued_at + timedelta(seconds=access_expires_in)
    refresh_expires_at = issued_at + timedelta(seconds=refresh_expires_in)
    plaintext_refresh_token = generate_refresh_token()

    refresh_token_row = CliAuthRefreshToken(
        cli_auth_session_id=cli_auth_session.id if cli_auth_session else None,
        user_id=user.id,
        token_hash=hash_cli_auth_token(plaintext_refresh_token),
        expires_at=refresh_expires_at,
        client_name=cli_auth_session.client_name if cli_auth_session else None,
        device_name=cli_auth_session.device_name if cli_auth_session else None,
        cli_version=cli_auth_session.cli_version if cli_auth_session else None,
        platform=cli_auth_session.platform if cli_auth_session else None,
    )
    db.add(refresh_token_row)
    db.flush()

    access_claims: dict[str, object] = {
        "sub": str(user.id),
        "email": user.email,
        "iss": settings.cli_auth_jwt_issuer,
        "aud": settings.cli_auth_jwt_audience,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(access_expires_at.timestamp()),
        "token_use": "access",
        "auth_source": "cli_auth",
        "refresh_token_id": str(refresh_token_row.id),
    }
    if cli_auth_session is not None:
        access_claims["cli_auth_session_id"] = str(cli_auth_session.id)

    access_token = _encode_cli_access_token(access_claims)
    return CliTokenPair(
        access_token=access_token,
        refresh_token=plaintext_refresh_token,
        refresh_token_id=refresh_token_row.id,
        expires_at=access_expires_at,
        expires_in=access_expires_in,
    )


def get_active_refresh_token_with_user(
    db: Session,
    *,
    refresh_token: str,
) -> tuple[CliAuthRefreshToken, User]:
    token_hash = hash_cli_auth_token(refresh_token)
    refresh_token_row = db.scalar(
        select(CliAuthRefreshToken).where(CliAuthRefreshToken.token_hash == token_hash)
    )
    if refresh_token_row is None:
        raise ValueError("invalid_refresh_token")

    now = utcnow()
    if refresh_token_row.revoked_at is not None:
        raise ValueError("invalid_refresh_token")
    if refresh_token_row.expires_at <= now:
        raise ValueError("invalid_refresh_token")

    user = db.get(User, refresh_token_row.user_id)
    if user is None:
        raise ValueError("invalid_refresh_token")

    return refresh_token_row, user


def rotate_cli_refresh_token(
    db: Session,
    *,
    refresh_token: str,
) -> tuple[CliTokenPair, User, CliAuthRefreshToken]:
    refresh_token_row, user = get_active_refresh_token_with_user(db, refresh_token=refresh_token)
    now = utcnow()
    refresh_token_row.last_used_at = now
    refresh_token_row.revoked_at = now

    session = None
    if refresh_token_row.cli_auth_session_id is not None:
        session = db.get(CliAuthSession, refresh_token_row.cli_auth_session_id)

    new_token_pair = issue_cli_token_pair(
        db,
        user=user,
        cli_auth_session=session,
    )
    refresh_token_row.replaced_by_token_id = new_token_pair.refresh_token_id
    return new_token_pair, user, refresh_token_row


def revoke_refresh_token_family(
    db: Session,
    *,
    refresh_token: str,
) -> CliAuthRefreshToken | None:
    token_hash = hash_cli_auth_token(refresh_token)
    refresh_token_row = db.scalar(
        select(CliAuthRefreshToken).where(CliAuthRefreshToken.token_hash == token_hash)
    )
    if refresh_token_row is None:
        return None

    now = utcnow()
    if refresh_token_row.cli_auth_session_id is not None:
        active_tokens = db.scalars(
            select(CliAuthRefreshToken).where(
                CliAuthRefreshToken.cli_auth_session_id == refresh_token_row.cli_auth_session_id,
                CliAuthRefreshToken.revoked_at.is_(None),
            )
        ).all()
        for token_row in active_tokens:
            token_row.revoked_at = now
    elif refresh_token_row.revoked_at is None:
        refresh_token_row.revoked_at = now

    return refresh_token_row
