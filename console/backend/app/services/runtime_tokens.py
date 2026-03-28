from __future__ import annotations

from hashlib import sha256
import secrets

from app.core.config import settings


def generate_runtime_token() -> str:
    return f"{settings.runtime_token_prefix}{secrets.token_urlsafe(settings.runtime_token_bytes)}"


def hash_runtime_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
