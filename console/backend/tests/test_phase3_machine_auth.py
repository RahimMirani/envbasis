from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy import select

from app.api.deps import ProjectAccess, get_current_user, get_project_access
from app.api.routes.machine_identities import (
    create_machine_credential,
    create_machine_identity,
    disable_machine_identity,
    enable_machine_identity,
    exchange_machine_identity_token,
    fetch_machine_secrets,
    list_machine_auth_history,
    revoke_machine_credential,
    rotate_machine_identity_secret,
    unlock_machine_identity,
)
from app.api.routes.projects import list_projects
from app.api.routes.secrets import list_secrets, push_secrets
from app.core.config import settings
from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission
from app.models.machine_identity_credential import MachineIdentityCredential
from app.models.organization import Organization
from app.schemas.machine_identity import MachineCredentialCreate, MachineIdentityCreate, MachineIdentityRotateSecretRequest, MachineTokenRequest
from app.schemas.secret import SecretPushRequest


def _access(project) -> ProjectAccess:
    return ProjectAccess(project=project, role="owner", can_push_pull_secrets=True, can_manage_runtime_tokens=True, can_manage_team=True, can_view_audit_logs=True)


def _request(ip: str = "192.0.2.10") -> Request:
    return Request({"type": "http", "http_version": "1.1", "method": "POST", "scheme": "https", "path": "/", "raw_path": b"/", "query_string": b"", "headers": [], "client": (ip, 1234), "server": ("test", 443)})


def _exchange(db, client_id: str, client_secret: str):
    return exchange_machine_identity_token(payload=MachineTokenRequest(client_id=client_id, client_secret=client_secret), request=_request(), response=Response(), db=db)


@pytest.fixture(autouse=True)
def machine_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "machine_auth_jwt_secret", "phase3-machine-secret-at-least-thirty-two-bytes")
    monkeypatch.setattr(settings, "machine_auth_max_failed_attempts", 3)
    monkeypatch.setattr(settings, "machine_auth_lockout_seconds", 600)


def test_multiple_credentials_overlap_revoke_and_auth_history(session_factory, seeder) -> None:
    owner = seeder.user("phase3-owner@example.com")
    project = seeder.project(owner, name="phase3-credentials")
    environment = seeder.environment(project, name="prod")
    access = _access(project)
    with session_factory() as db:
        created = create_machine_identity(payload=MachineIdentityCreate(name="agent", environment_id=environment.id), response=Response(), project_access=access, current_user=owner, db=db)
        second = create_machine_credential(identity_id=created.id, payload=MachineCredentialCreate(name="blue"), response=Response(), project_access=access, current_user=owner, db=db)
        second_token = _exchange(db, second.client_id, second.client_secret)
        assert fetch_machine_secrets(request=_request(), response=Response(), credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=second_token.access_token), db=db).machine_identity_id == created.id
        revoke_machine_credential(identity_id=created.id, credential_id=second.id, project_access=access, current_user=owner, db=db)
        with pytest.raises(HTTPException):
            fetch_machine_secrets(request=_request(), response=Response(), credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=second_token.access_token), db=db)

        rotated = rotate_machine_identity_secret(identity_id=created.id, payload=MachineIdentityRotateSecretRequest(overlap_seconds=3600), response=Response(), project_access=access, current_user=owner, db=db)
        old_during_overlap = _exchange(db, created.client_id, created.client_secret)
        assert old_during_overlap.access_token
        old = db.scalar(select(MachineIdentityCredential).where(MachineIdentityCredential.client_id == created.client_id))
        old.overlap_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            _exchange(db, created.client_id, created.client_secret)
        assert _exchange(db, rotated.client_id, rotated.client_secret).access_token
        history = list_machine_auth_history(identity_id=created.id, project_access=access, db=db)
    assert any(event.success for event in history)
    assert any(event.reason == "inactive_credential" for event in history)


def test_failure_lockout_unlock_disable_and_enable(session_factory, seeder) -> None:
    owner = seeder.user("phase3-lock-owner@example.com")
    project = seeder.project(owner, name="phase3-lockout")
    environment = seeder.environment(project, name="prod")
    access = _access(project)
    with session_factory() as db:
        created = create_machine_identity(payload=MachineIdentityCreate(name="locked-agent", environment_id=environment.id), response=Response(), project_access=access, current_user=owner, db=db)
        for _ in range(3):
            with pytest.raises(HTTPException):
                _exchange(db, created.client_id, "wrong-secret")
        with pytest.raises(HTTPException):
            _exchange(db, created.client_id, created.client_secret)
        unlocked = unlock_machine_identity(identity_id=created.id, project_access=access, current_user=owner, db=db)
        assert unlocked.failed_auth_attempts == 0
        assert _exchange(db, created.client_id, created.client_secret).access_token
        disabled = disable_machine_identity(identity_id=created.id, project_access=access, current_user=owner, db=db)
        assert disabled.disabled_at is not None
        with pytest.raises(HTTPException):
            _exchange(db, created.client_id, created.client_secret)
        enabled = enable_machine_identity(identity_id=created.id, project_access=access, current_user=owner, db=db)
        assert enabled.disabled_at is None
        assert _exchange(db, created.client_id, created.client_secret).access_token


def test_machine_token_works_with_standard_cli_project_and_secret_endpoints(session_factory, seeder) -> None:
    owner = seeder.user("phase3-cli-owner@example.com")
    project = seeder.project(owner, name="demo-api")
    environment = seeder.environment(project, name="production")
    access = _access(project)
    with session_factory() as db:
        push_secrets(project_id=project.id, environment_id=environment.id, payload=SecretPushRequest(secrets={"OPENAI_API_KEY": "hidden"}), project_access=access, current_user=owner, db=db)
        created = create_machine_identity(payload=MachineIdentityCreate(name="vercel-agent", environment_id=environment.id), response=Response(), project_access=access, current_user=owner, db=db)
        token = _exchange(db, created.client_id, created.client_secret)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token.access_token)
        machine_user = get_current_user(credentials=credentials, db=db)
        projects = list_projects(response=Response(), limit=100, offset=0, current_user=machine_user, db=db)
        machine_access = get_project_access(project_id=project.id, current_user=machine_user, db=db)
        secrets = list_secrets(project_id=project.id, environment_id=environment.id, response=Response(), limit=100, offset=0, key=None, path=None, recursive=False, tag=None, project_access=machine_access, current_user=machine_user, db=db)
    assert [item.name for item in projects] == ["demo-api"]
    assert [item.key for item in secrets.secrets] == ["OPENAI_API_KEY"]


def test_organization_identity_uses_assigned_role_across_attached_project(session_factory, seeder) -> None:
    owner = seeder.user("phase3-org-owner@example.com")
    project = seeder.project(owner, name="org-api")
    environment = seeder.environment(project, name="production")
    access = _access(project)
    with session_factory() as db:
        organization = Organization(name="Phase3 Org", owner_id=owner.id)
        db.add(organization); db.flush()
        project_row = db.get(type(project), project.id); project_row.organization_id = organization.id
        db.commit()
        access = _access(project_row)
        created = create_machine_identity(payload=MachineIdentityCreate(name="org-agent", environment_id=environment.id, scope="organization"), response=Response(), project_access=access, current_user=owner, db=db)
        role = AccessRole(project_id=project.id, name="org-agent-reader", is_builtin=False)
        db.add(role); db.flush()
        db.add_all([AccessRolePermission(role_id=role.id, resource="secrets", action="read", effect="allow", environment_id=environment.id, path="/", recursive=True), AccessRoleAssignment(role_id=role.id, machine_identity_id=created.id, created_by=owner.id)])
        db.commit()
        token = _exchange(db, created.client_id, created.client_secret)
        fetched = fetch_machine_secrets(request=_request(), response=Response(), project_id=project.id, environment_id=environment.id, path="/", recursive=True, credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token.access_token), db=db)
    assert fetched.project_id == project.id
