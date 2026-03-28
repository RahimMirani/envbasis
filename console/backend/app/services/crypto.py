from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet:
    if not settings.secrets_master_key:
        raise RuntimeError("SECRETS_MASTER_KEY is not configured.")

    try:
        return Fernet(settings.secrets_master_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("SECRETS_MASTER_KEY is invalid.") from exc


def encrypt_secret_value(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode("utf-8"))


def decrypt_secret_value(value: bytes) -> str:
    try:
        return _get_fernet().decrypt(value).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("Encrypted secret value could not be decrypted.") from exc


def encrypt_text(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode("utf-8"))


def decrypt_text(value: bytes) -> str:
    try:
        return _get_fernet().decrypt(value).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("Encrypted value could not be decrypted.") from exc
