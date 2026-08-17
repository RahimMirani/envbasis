from __future__ import annotations

from typing import Literal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.provider_credential import ProviderCredential
from app.services.project_encryption import decrypt_project_secret, encrypt_project_secret


SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "github"})
ProviderName = Literal["openai", "anthropic", "github"]


def normalize_provider_secret(secret: str) -> str:
    value = secret.strip()
    if not value:
        raise ValueError("Provider secret cannot be empty.")
    if len(value) > 4096:
        raise ValueError("Provider secret cannot exceed 4096 characters.")
    return value


def provider_key_last4(secret: str) -> str:
    if len(secret) <= 4:
        return secret
    return secret[-4:]


def get_provider_credential(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    provider: str,
) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.project_id == project_id,
            ProviderCredential.environment_id == environment_id,
            ProviderCredential.provider == provider,
        )
    )


def list_provider_credentials(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
) -> list[ProviderCredential]:
    return list(
        db.scalars(
            select(ProviderCredential)
            .where(
                ProviderCredential.project_id == project_id,
                ProviderCredential.environment_id == environment_id,
            )
            .order_by(ProviderCredential.provider.asc())
        ).all()
    )


def upsert_provider_credential(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    provider: str,
    secret: str,
    updated_by: uuid.UUID | None,
) -> ProviderCredential:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported provider.")
    plaintext = normalize_provider_secret(secret)
    encrypted_value, key_version = encrypt_project_secret(
        db,
        project_id=project_id,
        value=plaintext,
    )
    row = get_provider_credential(
        db,
        project_id=project_id,
        environment_id=environment_id,
        provider=provider,
    )
    if row is None:
        row = ProviderCredential(
            project_id=project_id,
            environment_id=environment_id,
            provider=provider,
            encrypted_secret=encrypted_value,
            encryption_key_version=key_version,
            key_last4=provider_key_last4(plaintext),
            updated_by=updated_by,
        )
        db.add(row)
        db.flush()
        return row

    row.encrypted_secret = encrypted_value
    row.encryption_key_version = key_version
    row.key_last4 = provider_key_last4(plaintext)
    row.updated_by = updated_by
    db.flush()
    return row


def decrypt_provider_credential(db: Session, credential: ProviderCredential) -> str:
    return decrypt_project_secret(
        db,
        project_id=credential.project_id,
        encrypted_value=credential.encrypted_secret,
        encryption_key_version=credential.encryption_key_version,
    )


def delete_provider_credential(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    provider: str,
) -> bool:
    row = get_provider_credential(
        db,
        project_id=project_id,
        environment_id=environment_id,
        provider=provider,
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
