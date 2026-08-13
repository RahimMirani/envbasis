from __future__ import annotations

from datetime import datetime, timedelta, timezone
from inspect import signature

from fastapi import HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy import select

from app.api.deps import ProjectAccess, require_runtime_token_management
from app.api.routes.machine_identities import (
    create_machine_identity,
    exchange_machine_identity_token,
    fetch_machine_secrets,
    list_machine_identities,
    revoke_machine_identity,
    rotate_machine_identity_secret,
    update_machine_identity,
)
from app.api.routes.secrets import push_secrets
from app.core.config import settings
from app.models.machine_identity import MachineIdentity
from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission
from app.schemas.machine_identity import (
    MachineIdentityCreate,
    MachineIdentityRotateSecretRequest,
    MachineIdentityUpdate,
    MachineTokenRequest,
)
from app.schemas.secret import SecretPushRequest
from app.services.machine_identities import decode_machine_access_token


@pytest.fixture(autouse=True)
def machine_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "machine_auth_jwt_secret",
        "test-machine-jwt-secret-that-is-at-least-32-bytes",
    )
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


def _request(*, client_ip: str, path: str = "/") -> Request:
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


def test_machine_identity_one_time_credential_exchange_and_scoped_secret_fetch(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-machine-flow@example.com")
    project = seeder.project(owner, name="machine-flow-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(
                secrets={
                    "OPENAI_API_KEY": "sk-machine",
                    "DATABASE_URL": "postgres://private",
                }
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    create_response_headers = Response()
    credential_expiry = datetime.now(timezone.utc) + timedelta(days=30)
    with session_factory() as db:
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="public-agent-prod",
                environment_id=environment.id,
                allowed_secret_keys=["OPENAI_*"],
                trusted_cidrs=["10.0.0.15/8"],
                access_token_ttl_seconds=600,
                credential_expires_at=credential_expiry,
            ),
            response=create_response_headers,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert created.client_id.startswith("envb_mi_")
    assert created.client_secret.startswith("envb_mis_")
    assert created.access_token_ttl_seconds == 600
    assert created.trusted_cidrs == ["10.0.0.0/8"]
    assert create_response_headers.headers["cache-control"] == "no-store"

    with session_factory() as db:
        stored = db.get(MachineIdentity, created.id)
        listed = list_machine_identities(project_access=access, db=db)

    assert stored is not None
    assert stored.client_secret_hash != created.client_secret
    assert created.client_secret not in stored.client_secret_hash
    assert len(listed) == 1
    assert not hasattr(listed[0], "client_secret")

    token_headers = Response()
    with session_factory() as db:
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(client_ip="10.20.30.40", path="/machine-identities/token"),
            response=token_headers,
            db=db,
        )

    claims = decode_machine_access_token(token.access_token)
    assert token.expires_in == 600
    assert int(claims["exp"]) - int(claims["iat"]) == 600
    assert claims["credential_version"] == 1
    assert token_headers.headers["cache-control"] == "no-store"

    secret_headers = Response()
    with session_factory() as db:
        fetched = fetch_machine_secrets(
            request=_request(client_ip="10.99.1.2", path="/machine/secrets"),
            response=secret_headers,
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token.access_token,
            ),
            db=db,
        )

    assert fetched.secrets == {"OPENAI_API_KEY": "sk-machine"}
    assert secret_headers.headers["cache-control"] == "no-store"
    assert seeder.audit_actions(project)[-2:] == [
        "machine_identity.authenticated",
        "machine_identity.secrets_accessed",
    ]


def test_machine_identity_uses_folder_scoped_rbac(session_factory, seeder) -> None:
    owner = seeder.user("owner-machine-rbac@example.com")
    project = seeder.project(owner, name="machine-rbac")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)
    with session_factory() as db:
        push_secrets(project_id=project.id, environment_id=environment.id, payload=SecretPushRequest(secrets={"PUBLIC_KEY": "visible"}, path="/public"), project_access=access, current_user=owner, db=db)
        push_secrets(project_id=project.id, environment_id=environment.id, payload=SecretPushRequest(secrets={"PRIVATE_KEY": "hidden"}, path="/private"), project_access=access, current_user=owner, db=db)
        created = create_machine_identity(payload=MachineIdentityCreate(name="rbac-agent", environment_id=environment.id), response=Response(), project_access=access, current_user=owner, db=db)
        role = AccessRole(project_id=project.id, name="public-only", is_builtin=False)
        db.add(role)
        db.flush()
        db.add_all([
            AccessRolePermission(role_id=role.id, resource="secrets", action="read", effect="allow", environment_id=environment.id, path="/public", recursive=True),
            AccessRoleAssignment(role_id=role.id, machine_identity_id=created.id, created_by=owner.id),
        ])
        db.commit()
        token = exchange_machine_identity_token(payload=MachineTokenRequest(client_id=created.client_id, client_secret=created.client_secret), request=_request(client_ip="192.0.2.10"), response=Response(), db=db)
        fetched = fetch_machine_secrets(request=_request(client_ip="192.0.2.10"), response=Response(), credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token.access_token), db=db)
    assert fetched.secrets == {"PUBLIC_KEY": "visible"}


def test_scope_updates_apply_to_already_issued_machine_tokens(session_factory, seeder) -> None:
    owner = seeder.user("owner-machine-scope@example.com")
    project = seeder.project(owner, name="machine-scope-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(
                secrets={
                    "OPENAI_API_KEY": "sk-scope",
                    "DATABASE_URL": "postgres://scope",
                }
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="scope-agent",
                environment_id=environment.id,
                allowed_secret_keys=["OPENAI_*"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(client_ip="192.0.2.10"),
            response=Response(),
            db=db,
        )

    with session_factory() as db:
        updated = update_machine_identity(
            identity_id=created.id,
            payload=MachineIdentityUpdate(
                allowed_secret_keys=["DATABASE_*"],
                access_token_ttl_seconds=900,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert updated.allowed_secret_keys == ["DATABASE_*"]
    assert updated.access_token_ttl_seconds == 900

    with session_factory() as db:
        fetched = fetch_machine_secrets(
            request=_request(client_ip="192.0.2.10"),
            response=Response(),
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=token.access_token,
            ),
            db=db,
        )

    assert fetched.secrets == {"DATABASE_URL": "postgres://scope"}


def test_secret_rotation_and_revocation_immediately_invalidate_access_tokens(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-machine-rotation@example.com")
    project = seeder.project(owner, name="machine-rotation-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)
    credential_expiry = datetime.now(timezone.utc) + timedelta(days=7)

    with session_factory() as db:
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="rotation-agent",
                environment_id=environment.id,
                credential_expires_at=credential_expiry,
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )
    with session_factory() as db:
        first_token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(client_ip="198.51.100.5"),
            response=Response(),
            db=db,
        )

    rotate_headers = Response()
    with session_factory() as db:
        rotated = rotate_machine_identity_secret(
            identity_id=created.id,
            payload=MachineIdentityRotateSecretRequest(),
            response=rotate_headers,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert rotated.credential_version == 2
    assert rotated.client_secret != created.client_secret
    assert rotated.credential_expires_at is not None
    assert rotated.credential_expires_at.replace(tzinfo=timezone.utc) == credential_expiry
    assert rotate_headers.headers["cache-control"] == "no-store"

    with session_factory() as db:
        with pytest.raises(HTTPException) as old_token_error:
            fetch_machine_secrets(
                request=_request(client_ip="198.51.100.5"),
                response=Response(),
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=first_token.access_token,
                ),
                db=db,
            )
    assert old_token_error.value.status_code == 401

    with session_factory() as db:
        with pytest.raises(HTTPException) as old_secret_error:
            exchange_machine_identity_token(
                payload=MachineTokenRequest(
                    client_id=created.client_id,
                    client_secret=created.client_secret,
                ),
                request=_request(client_ip="198.51.100.5"),
                response=Response(),
                db=db,
            )
    assert old_secret_error.value.status_code == 401

    with session_factory() as db:
        second_token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=rotated.client_id,
                client_secret=rotated.client_secret,
            ),
            request=_request(client_ip="198.51.100.5"),
            response=Response(),
            db=db,
        )
    with session_factory() as db:
        revoked = revoke_machine_identity(
            identity_id=created.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert revoked.revoked_at is not None
    assert revoked.credential_version == 3

    with session_factory() as db:
        with pytest.raises(HTTPException) as revoked_token_error:
            fetch_machine_secrets(
                request=_request(client_ip="198.51.100.5"),
                response=Response(),
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=second_token.access_token,
                ),
                db=db,
            )
    assert revoked_token_error.value.status_code == 401


def test_trusted_cidrs_are_enforced_on_exchange_and_every_secret_request(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-machine-cidr@example.com")
    project = seeder.project(owner, name="machine-cidr-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    with session_factory() as db:
        created = create_machine_identity(
            payload=MachineIdentityCreate(
                name="cidr-agent",
                environment_id=environment.id,
                trusted_cidrs=["203.0.113.0/24"],
            ),
            response=Response(),
            project_access=access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db:
        with pytest.raises(HTTPException) as exchange_error:
            exchange_machine_identity_token(
                payload=MachineTokenRequest(
                    client_id=created.client_id,
                    client_secret=created.client_secret,
                ),
                request=_request(client_ip="198.51.100.20"),
                response=Response(),
                db=db,
            )
    assert exchange_error.value.status_code == 401

    with session_factory() as db:
        token = exchange_machine_identity_token(
            payload=MachineTokenRequest(
                client_id=created.client_id,
                client_secret=created.client_secret,
            ),
            request=_request(client_ip="203.0.113.20"),
            response=Response(),
            db=db,
        )
    with session_factory() as db:
        with pytest.raises(HTTPException) as fetch_error:
            fetch_machine_secrets(
                request=_request(client_ip="198.51.100.20"),
                response=Response(),
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token.access_token,
                ),
                db=db,
            )
    assert fetch_error.value.status_code == 403


def test_machine_identity_validates_ttl_cidr_and_credential_expiry(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-machine-validation@example.com")
    project = seeder.project(owner, name="machine-validation-project")
    environment = seeder.environment(project, name="prod")
    access = _owner_access(project)

    invalid_payloads = (
        MachineIdentityCreate(
            name="short-ttl",
            environment_id=environment.id,
            access_token_ttl_seconds=299,
        ),
        MachineIdentityCreate(
            name="invalid-cidr",
            environment_id=environment.id,
            trusted_cidrs=["not-a-network"],
        ),
        MachineIdentityCreate(
            name="expired-credential",
            environment_id=environment.id,
            credential_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ),
    )
    for payload in invalid_payloads:
        with session_factory() as db:
            with pytest.raises(HTTPException) as error:
                create_machine_identity(
                    payload=payload,
                    response=Response(),
                    project_access=access,
                    current_user=owner,
                    db=db,
                )
        assert error.value.status_code == 422


def test_machine_identity_management_routes_require_runtime_token_management() -> None:
    for route in (create_machine_identity, list_machine_identities):
        dependency = signature(route).parameters["project_access"].default
        assert dependency.dependency is require_runtime_token_management
