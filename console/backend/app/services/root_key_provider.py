from __future__ import annotations

from dataclasses import dataclass
import base64
from typing import Any, Protocol
import uuid

from app.core.config import settings
from app.services.crypto import (
    generate_data_encryption_key,
    unwrap_data_encryption_key,
    wrap_data_encryption_key,
)


LOCAL_PROVIDER = "local"
AWS_KMS_PROVIDER = "aws_kms"


@dataclass(frozen=True)
class GeneratedProjectDataKey:
    plaintext_key: bytes
    wrapped_key: bytes
    provider: str
    key_id: str | None


class RootKeyProvider(Protocol):
    def generate_project_data_key(self, *, project_id: uuid.UUID) -> GeneratedProjectDataKey: ...

    def unwrap_project_data_key(
        self,
        *,
        project_id: uuid.UUID,
        wrapped_key: bytes,
        key_id: str | None,
    ) -> bytes: ...


def _encryption_context(project_id: uuid.UUID) -> dict[str, str]:
    return {
        "envbasis:purpose": "project-data-encryption-key",
        "envbasis:project_id": str(project_id),
    }


class LocalRootKeyProvider:
    def generate_project_data_key(self, *, project_id: uuid.UUID) -> GeneratedProjectDataKey:
        del project_id
        plaintext_key = generate_data_encryption_key()
        return GeneratedProjectDataKey(
            plaintext_key=plaintext_key,
            wrapped_key=wrap_data_encryption_key(plaintext_key),
            provider=LOCAL_PROVIDER,
            key_id=None,
        )

    def unwrap_project_data_key(
        self,
        *,
        project_id: uuid.UUID,
        wrapped_key: bytes,
        key_id: str | None,
    ) -> bytes:
        del project_id, key_id
        return unwrap_data_encryption_key(wrapped_key)


def _build_aws_kms_client() -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on deployment extras
        raise RuntimeError(
            "boto3 is required when SECRETS_ROOT_KEY_PROVIDER=aws_kms."
        ) from exc

    client_kwargs: dict[str, str] = {}
    if settings.aws_kms_region:
        client_kwargs["region_name"] = settings.aws_kms_region
    if settings.aws_kms_endpoint_url:
        client_kwargs["endpoint_url"] = settings.aws_kms_endpoint_url
    return boto3.client("kms", **client_kwargs)


class AwsKmsRootKeyProvider:
    def __init__(self, *, key_id: str | None = None) -> None:
        self.key_id = key_id or settings.aws_kms_key_id
        if not self.key_id:
            raise RuntimeError("AWS_KMS_KEY_ID is required for AWS KMS root-key operations.")

    def generate_project_data_key(self, *, project_id: uuid.UUID) -> GeneratedProjectDataKey:
        response = _build_aws_kms_client().generate_data_key(
            KeyId=self.key_id,
            KeySpec="AES_256",
            EncryptionContext=_encryption_context(project_id),
        )
        plaintext = bytes(response["Plaintext"])
        if len(plaintext) != 32:
            raise RuntimeError("AWS KMS returned an invalid data-key length.")
        return GeneratedProjectDataKey(
            plaintext_key=base64.urlsafe_b64encode(plaintext),
            wrapped_key=bytes(response["CiphertextBlob"]),
            provider=AWS_KMS_PROVIDER,
            key_id=str(response.get("KeyId") or self.key_id),
        )

    def unwrap_project_data_key(
        self,
        *,
        project_id: uuid.UUID,
        wrapped_key: bytes,
        key_id: str | None,
    ) -> bytes:
        request: dict[str, Any] = {
            "CiphertextBlob": wrapped_key,
            "EncryptionContext": _encryption_context(project_id),
        }
        if key_id:
            request["KeyId"] = key_id
        response = _build_aws_kms_client().decrypt(**request)
        plaintext = bytes(response["Plaintext"])
        if len(plaintext) != 32:
            raise RuntimeError("AWS KMS returned an invalid data-key length.")
        return base64.urlsafe_b64encode(plaintext)


def get_active_root_key_provider() -> RootKeyProvider:
    if settings.secrets_root_key_provider == AWS_KMS_PROVIDER:
        return AwsKmsRootKeyProvider()
    return LocalRootKeyProvider()


def get_root_key_provider_for_wrapped_key(
    *,
    provider: str,
    key_id: str | None,
) -> RootKeyProvider:
    if provider == LOCAL_PROVIDER:
        return LocalRootKeyProvider()
    if provider == AWS_KMS_PROVIDER:
        return AwsKmsRootKeyProvider(key_id=key_id)
    raise RuntimeError(f"Unsupported project-key wrapping provider: {provider}.")
