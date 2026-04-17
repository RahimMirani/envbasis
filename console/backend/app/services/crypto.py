from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PLACEHOLDER_MASTER_KEY = "replace-with-fernet-key"


def _get_fernet() -> Fernet:
    key = settings.secrets_master_key
    if not key:
        raise RuntimeError("SECRETS_MASTER_KEY is not configured.")
    if key == _PLACEHOLDER_MASTER_KEY:
        raise RuntimeError(
            "SECRETS_MASTER_KEY is set to the placeholder value. "
            "Generate a real key with `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
        )

    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "SECRETS_MASTER_KEY is not a valid Fernet key (expected a 32-byte url-safe base64 string)."
        ) from exc


def ensure_secrets_master_key_configured() -> None:
    _get_fernet()


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
