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


PROXY_TOKEN = "test-proxy-service-token"


@pytest.fixture(autouse=True)
def machine_and_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "machine_auth_jwt_secret",
        "test-machine-jwt-secret-that-is-at-least-32-bytes",
    )
    monkeypatch.setattr(settings, "proxy_service_token", PROXY_TOKEN)


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def _request(*, client_ip: str = "127.0.0.1", path: str = "/"):
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


def test_upsert_list_and_delete_provider_credential(session_factory, seeder) -> None:
    owner = seeder.user("owner-provider-keys@example.com")
    project = seeder.project(owner, name="provider-keys")
    environment = seeder.environment(project, name="dev")
    access = _owner_access(project)

    with session_factory() as db:
        saved = upsert_environment_provider_credential(
            environment_id=environment.id,
            payload=ProviderCredentialUpsert(provider="openai", secret="sk-live-openai-key-9xyz"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        listed = list_environment_provider_credentials(
            environment_id=environment.id,
            project_access=access,
            db=db,
        )

    assert saved.provider == "openai"
    assert saved.key_last4 == "9xyz"
    assert listed.items[0].key_last4 == "9xyz"
    assert all(not hasattr(item, "secret") for item in listed.items)

    with session_factory() as db:
        stored = db.scalar(select(ProviderCredential))
        assert stored is not None
        assert b"sk-live-openai-key-9xyz" not in stored.encrypted_secret
        actions = list(
            db.scalars(select(AuditLog.action).where(AuditLog.project_id == project.id)).all()
        )
    assert "provider_credential.upserted" in actions

    with session_factory() as db:
        deleted = delete_environment_provider_credential(
            environment_id=environment.id,
            provider="openai",
            project_access=access,
            current_user=owner,
            db=db,
        )
    assert deleted.detail == "Provider credential deleted."


def test_proxy_resolves_environment_key_for_machine_with_proxy_use(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-resolve@example.com")
    project = seeder.project(owner, name="proxy-resolve")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        upsert_environment_provider_credential(
            environment_id=environment.id,
            payload=ProviderCredentialUpsert(provider="openai", secret="sk-platform-openai"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="agent",
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
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(),
            response=Response(),
            db=db,
        )
        resolved = resolve_proxy_credential(
            payload=ProxyCredentialResolveRequest(
                machine_access_token=token.access_token,
                provider="openai",
            ),
            db=db,
            authorization=f"Bearer {PROXY_TOKEN}",
        )

    assert resolved.provider == "openai"
    assert resolved.secret == "sk-platform-openai"


def test_proxy_resolve_requires_proxy_use_action(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-denied@example.com")
    project = seeder.project(owner, name="proxy-denied")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        upsert_environment_provider_credential(
            environment_id=environment.id,
            payload=ProviderCredentialUpsert(provider="openai", secret="sk-hidden"),
            project_access=access,
            current_user=owner,
            db=db,
        )
        created = create_machine_identity(
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
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(),
            response=Response(),
            db=db,
        )
        with pytest.raises(HTTPException) as exc:
            resolve_proxy_credential(
                payload=ProxyCredentialResolveRequest(
                    machine_access_token=token.access_token,
                    provider="openai",
                ),
                db=db,
                authorization=f"Bearer {PROXY_TOKEN}",
            )
    assert exc.value.status_code == 403


def test_proxy_resolve_rejects_bad_service_token(session_factory, seeder) -> None:
    owner = seeder.user("owner-proxy-auth@example.com")
    project = seeder.project(owner, name="proxy-auth")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="agent",
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
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(),
            response=Response(),
            db=db,
        )
        with pytest.raises(HTTPException) as exc:
            resolve_proxy_credential(
                payload=ProxyCredentialResolveRequest(
                    machine_access_token=token.access_token,
                    provider="openai",
                ),
                db=db,
                authorization="Bearer wrong-token",
            )
    assert exc.value.status_code == 401


def test_organization_scoped_identity_cannot_enable_proxy_use() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MachineIdentityCreate(
            name="org-agent",
            scope="organization",
            allowed_actions=["proxy:use"],
        )
