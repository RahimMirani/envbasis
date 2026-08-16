from __future__ import annotations

from fastapi import HTTPException, Response
import pytest
from sqlalchemy import select

from app.api.deps import ProjectAccess
from app.api.routes.machine_identities import (
    create_machine_identity,
    exchange_machine_identity_token,
)
from app.api.routes.provider_credentials import (
    delete_environment_provider_credential,
    list_environment_provider_credentials,
    upsert_environment_provider_credential,
)
from app.api.routes.proxy_internal import resolve_proxy_credential
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.provider_credential import ProviderCredential
from app.schemas.machine_identity import MachineIdentityCreate, MachineTokenRequest
from app.schemas.provider_credential import (
    ProviderCredentialUpsert,
    ProxyCredentialResolveRequest,
)


PROXY_SERVICE_TOKEN = "test-proxy-service-token-value"


@pytest.fixture(autouse=True)
def proxy_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "machine_auth_jwt_secret",
        "test-machine-jwt-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(settings, "proxy_service_token", PROXY_SERVICE_TOKEN)
    monkeypatch.setattr(settings, "machine_auth_min_access_token_ttl_seconds", 300)
    monkeypatch.setattr(settings, "machine_auth_default_access_token_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "machine_auth_max_access_token_ttl_seconds", 86400)


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def _request(*, client_ip: str = "10.20.30.40", path: str = "/") :
    from fastapi import Request

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": (client_ip, 43210),
            "server": ("testserver", 443),
        }
    )


def test_provider_credential_crud_exposes_last4_only(session_factory, seeder) -> None:
    owner = seeder.user("owner-provider-keys@example.com")
    project = seeder.project(owner, name="provider-keys")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        created = upsert_environment_provider_credential(
            environment_id=environment.id,
            payload=ProviderCredentialUpsert(provider="openai", secret="sk-live-abcdef1234"),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        assert created.provider == "openai"
        assert created.key_last4 == "1234"
        assert "sk-live" not in created.model_dump_json()

        listed = list_environment_provider_credentials(
            environment_id=environment.id,
            response=Response(),
            project_access=access,
            db=db,
        )
        assert len(listed.credentials) == 1
        assert listed.credentials[0].key_last4 == "1234"

        row = db.scalar(select(ProviderCredential))
        assert row is not None
        assert b"sk-live" not in row.encrypted_value

        audits = db.scalars(select(AuditLog).where(AuditLog.action == "provider_credential.upserted")).all()
        assert len(audits) == 1
        assert audits[0].metadata_json["key_last4"] == "1234"
        assert "secret" not in audits[0].metadata_json

        deleted = delete_environment_provider_credential(
            environment_id=environment.id,
            provider="openai",
            project_access=access,
            current_user=owner,
            db=db,
        )
        assert deleted.detail == "Provider credential deleted."
        assert db.scalar(select(ProviderCredential)) is None


def test_proxy_resolve_injects_configured_credential(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-resolve@example.com")
    project = seeder.project(owner, name="proxy-resolve")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        upsert_environment_provider_credential(
            environment_id=environment.id,
            payload=ProviderCredentialUpsert(provider="openai", secret="sk-project-secret"),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        identity = create_machine_identity(
            payload=MachineIdentityCreate(
                name="proxy-agent",
                environment_id=environment.id,
                allowed_actions=["proxy:use"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=identity.client_id,
                client_secret=identity.client_secret,
            ),
            request=_request(path="/machine-identities/token"),
            response=Response(),
            db=db,
        )

        resolved = resolve_proxy_credential(
            payload=ProxyCredentialResolveRequest(
                machine_access_token=token.access_token,
                provider="openai",
            ),
            response=Response(),
            authorization=f"Bearer {PROXY_SERVICE_TOKEN}",
            db=db,
        )
        assert resolved.credential == "sk-project-secret"
        assert resolved.provider == "openai"
        assert resolved.project_id == project.id
        assert resolved.environment_id == environment.id
        assert resolved.machine_identity_id == identity.id


def test_proxy_resolve_rejects_machine_token_as_service_auth(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-reject@example.com")
    project = seeder.project(owner, name="proxy-reject")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        identity = create_machine_identity(
            payload=MachineIdentityCreate(
                name="proxy-agent",
                environment_id=environment.id,
                allowed_actions=["proxy:use", "secrets:read"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=identity.client_id,
                client_secret=identity.client_secret,
            ),
            request=_request(path="/machine-identities/token"),
            response=Response(),
            db=db,
        )
        with pytest.raises(HTTPException) as exc:
            resolve_proxy_credential(
                payload=ProxyCredentialResolveRequest(
                    machine_access_token=token.access_token,
                    provider="openai",
                ),
                response=Response(),
                authorization=f"Bearer {token.access_token}",
                db=db,
            )
        assert exc.value.status_code == 401
        assert exc.value.detail["code"] == "invalid_proxy_service_token"


def test_proxy_resolve_requires_proxy_use_and_configured_key(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-forbidden@example.com")
    project = seeder.project(owner, name="proxy-forbidden")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        identity = create_machine_identity(
            payload=MachineIdentityCreate(
                name="secrets-only",
                environment_id=environment.id,
                allowed_actions=["secrets:read"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=identity.client_id,
                client_secret=identity.client_secret,
            ),
            request=_request(path="/machine-identities/token"),
            response=Response(),
            db=db,
        )
        with pytest.raises(HTTPException) as exc:
            resolve_proxy_credential(
                payload=ProxyCredentialResolveRequest(
                    machine_access_token=token.access_token,
                    provider="openai",
                ),
                response=Response(),
                authorization=f"Bearer {PROXY_SERVICE_TOKEN}",
                db=db,
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "proxy_use_forbidden"

        proxy_identity = create_machine_identity(
            payload=MachineIdentityCreate(
                name="proxy-only",
                environment_id=environment.id,
                allowed_actions=["proxy:use"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
        proxy_token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=proxy_identity.client_id,
                client_secret=proxy_identity.client_secret,
            ),
            request=_request(path="/machine-identities/token"),
            response=Response(),
            db=db,
        )
        with pytest.raises(HTTPException) as missing:
            resolve_proxy_credential(
                payload=ProxyCredentialResolveRequest(
                    machine_access_token=proxy_token.access_token,
                    provider="openai",
                ),
                response=Response(),
                authorization=f"Bearer {PROXY_SERVICE_TOKEN}",
                db=db,
            )
        assert missing.value.status_code == 404
        assert missing.value.detail["code"] == "provider_not_configured"


def test_organization_scoped_identity_cannot_enable_proxy_use() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MachineIdentityCreate(
            name="org-agent",
            scope="organization",
            allowed_actions=["proxy:use"],
        )
