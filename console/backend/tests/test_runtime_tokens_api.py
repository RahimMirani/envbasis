from __future__ import annotations

from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
import pytest

from app.api.deps import ProjectAccess
from app.api.routes.runtime import fetch_runtime_secrets
from app.api.routes.runtime_tokens import (
    create_runtime_token,
    list_runtime_tokens,
    reveal_runtime_token,
    revoke_runtime_token,
    share_runtime_token,
)
from app.api.routes.secrets import push_secrets
from app.models.runtime_token import RuntimeToken
from app.schemas.runtime_token import RuntimeTokenCreateRequest
from app.schemas.runtime_token_share import RuntimeTokenShareRequest
from app.schemas.secret import SecretPushRequest
from app.services.crypto import encrypt_text


def _project_access(
    project,
    *,
    role: str,
    can_push_pull_secrets: bool = False,
    can_manage_runtime_tokens: bool = False,
    can_manage_team: bool = False,
    can_view_audit_logs: bool = False,
) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role=role,
        can_push_pull_secrets=can_push_pull_secrets,
        can_manage_runtime_tokens=can_manage_runtime_tokens,
        can_manage_team=can_manage_team,
        can_view_audit_logs=can_view_audit_logs,
    )


def test_runtime_token_create_fetch_list_and_revoke(session_factory, seeder) -> None:
    owner = seeder.user("owner-runtime@example.com")
    project = seeder.project(owner, name="runtime-project")
    environment = seeder.environment(project, name="prod")
    access = _project_access(
        project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )

    with session_factory() as db:
        push_response = push_secrets(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretPushRequest(secrets={"OPENAI_API_KEY": "sk-runtime"}),
            project_access=access,
            current_user=owner,
            db=db,
        )
        assert push_response.changed == 1

    with session_factory() as db:
        http_response = Response()
        create_response = create_runtime_token(
            project_id=project.id,
            environment_id=environment.id,
            payload=RuntimeTokenCreateRequest(name="agent-prod"),
            response=http_response,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert create_response.name == "agent-prod"
    assert create_response.plaintext_token.startswith("envb_rt_")
    assert create_response.is_revealable is False
    assert http_response.headers["cache-control"] == "no-store"

    with session_factory() as db:
        list_response = list_runtime_tokens(
            project_id=project.id,
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert [token.name for token in list_response] == ["agent-prod"]

    with session_factory() as db:
        runtime_fetch_response = fetch_runtime_secrets(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=create_response.plaintext_token,
            ),
            db=db,
        )

    assert runtime_fetch_response.secrets == {"OPENAI_API_KEY": "sk-runtime"}

    stored_token = seeder.runtime_token(create_response.id)
    assert stored_token is not None
    assert stored_token.last_used_at is not None
    assert stored_token.encrypted_token is None
    assert stored_token.token_hash != create_response.plaintext_token

    with session_factory() as db:
        with pytest.raises(HTTPException) as reveal_error:
            reveal_runtime_token(
                token_id=create_response.id,
                response=Response(),
                current_user=owner,
                db=db,
            )
        assert reveal_error.value.status_code == 409
        assert reveal_error.value.detail == (
            "This credential was displayed once and cannot be shared or revealed. "
            "Create a separate token for each machine."
        )

    with session_factory() as db:
        revoke_response = revoke_runtime_token(
            token_id=create_response.id,
            current_user=owner,
            db=db,
        )

    assert revoke_response.detail == "Runtime token revoked."
    assert seeder.runtime_token(create_response.id) is None

    with session_factory() as db:
        try:
            fetch_runtime_secrets(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=create_response.plaintext_token,
                ),
                db=db,
            )
        except Exception as exc:  # pragma: no branch
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 401
            assert exc.detail == "Invalid runtime token."
        else:  # pragma: no cover
            raise AssertionError("Expected revoked runtime token to stop working")


def test_shared_member_can_list_and_reveal_shared_runtime_token(session_factory, seeder) -> None:
    owner = seeder.user("owner-share@example.com")
    member = seeder.user("member-share@example.com")
    project = seeder.project(owner, name="sharing-project")
    environment = seeder.environment(project, name="dev")
    seeder.add_member(project=project, user=member, invited_by=owner)
    owner_access = _project_access(
        project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )
    member_access = _project_access(project, role="member")

    with session_factory() as db:
        http_response = Response()
        create_response = create_runtime_token(
            project_id=project.id,
            environment_id=environment.id,
            payload=RuntimeTokenCreateRequest(name="shared-agent"),
            response=http_response,
            project_access=owner_access,
            current_user=owner,
            db=db,
        )

    # Simulate a token created before hash-only credentials were introduced.
    with session_factory() as db:
        legacy_token = db.get(RuntimeToken, create_response.id)
        assert legacy_token is not None
        legacy_token.encrypted_token = encrypt_text(create_response.plaintext_token)
        db.commit()

    with session_factory() as db:
        share_response = share_runtime_token(
            project_id=project.id,
            token_id=create_response.id,
            payload=RuntimeTokenShareRequest(email=member.email),
            project_access=owner_access,
            current_user=owner,
            db=db,
        )

    assert share_response.email == member.email

    with session_factory() as db:
        member_list_response = list_runtime_tokens(
            project_id=project.id,
            project_access=member_access,
            current_user=member,
            db=db,
        )

    assert [str(token.id) for token in member_list_response] == [str(create_response.id)]
    assert member_list_response[0].is_revealable is True

    with session_factory() as db:
        reveal_response = reveal_runtime_token(
            token_id=create_response.id,
            response=Response(),
            current_user=member,
            db=db,
        )

    assert str(reveal_response.token_id) == str(create_response.id)
    assert reveal_response.plaintext_token == create_response.plaintext_token
