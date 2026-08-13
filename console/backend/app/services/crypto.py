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


def generate_data_encryption_key() -> bytes:
    return Fernet.generate_key()


def wrap_data_encryption_key(data_key: bytes) -> bytes:
    return _get_fernet().encrypt(data_key)


def unwrap_data_encryption_key(wrapped_key: bytes) -> bytes:
    try:
        data_key = _get_fernet().decrypt(wrapped_key)
        Fernet(data_key)
        return data_key
    except (InvalidToken, TypeError, ValueError) as exc:
        raise RuntimeError("Project encryption key could not be unwrapped.") from exc


def encrypt_with_data_key(value: str, data_key: bytes) -> bytes:
    try:
        return Fernet(data_key).encrypt(value.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Project encryption key is invalid.") from exc


def decrypt_with_data_key(value: bytes, data_key: bytes) -> str:
    try:
        return Fernet(data_key).decrypt(value).decode("utf-8")
    except (InvalidToken, TypeError, ValueError) as exc:
        raise RuntimeError("Encrypted project secret could not be decrypted.") from exc


def encrypt_text(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode("utf-8"))


def decrypt_text(value: bytes) -> str:
    try:
        return _get_fernet().decrypt(value).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("Encrypted value could not be decrypted.") from exc
