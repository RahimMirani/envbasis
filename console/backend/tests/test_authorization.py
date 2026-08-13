from __future__ import annotations

from dataclasses import fields
from itertools import product
from pathlib import Path

from fastapi import HTTPException
import pytest

from app.api.deps import (
    ProjectAccess,
    ROLE_MEMBER,
    ROLE_OWNER,
    get_project_access,
    require_audit_log_access,
    require_project_owner,
    require_runtime_token_management,
    require_secret_management,
    require_team_management,
)
from app.models.project import Project
from app.services.member_permissions import MEMBER_PERMISSION_FIELDS


MEMBER_PERMISSION_COMBINATIONS = list(product((False, True), repeat=4))
PERMISSION_MODEL_DOCUMENT = Path(__file__).parents[3] / "docs" / "PERMISSIONS.md"


def test_permission_model_documentation_covers_active_permission_fields() -> None:
    project_access_fields = tuple(
        field.name
        for field in fields(ProjectAccess)
        if field.name.startswith("can_")
    )
    assert project_access_fields == MEMBER_PERMISSION_FIELDS

    permission_document = PERMISSION_MODEL_DOCUMENT.read_text(encoding="utf-8")
    for permission in MEMBER_PERMISSION_FIELDS:
        assert f"`{permission}`" in permission_document
    for role in (ROLE_OWNER, ROLE_MEMBER):
        assert f"`{role}`" in permission_document
    for visibility in ("owner_only", "members", "specific"):
        assert f"`{visibility}`" in permission_document


def _assert_guard(*, guard, access, allowed: bool) -> None:
    if allowed:
        assert guard(access) is access
        return

    with pytest.raises(HTTPException) as error:
        guard(access)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    (
        "can_push_pull_secrets",
        "can_manage_runtime_tokens",
        "can_manage_team",
        "can_view_audit_logs",
    ),
    MEMBER_PERMISSION_COMBINATIONS,
)
def test_member_authorization_matrix(
    session_factory,
    seeder,
    can_push_pull_secrets: bool,
    can_manage_runtime_tokens: bool,
    can_manage_team: bool,
    can_view_audit_logs: bool,
) -> None:
    owner = seeder.user("owner-permission-matrix@example.com")
    member = seeder.user("member-permission-matrix@example.com")
    project = seeder.project(owner, name="permission-matrix-project")
    seeder.add_member(
        project=project,
        user=member,
        can_push_pull_secrets=can_push_pull_secrets,
        can_manage_runtime_tokens=can_manage_runtime_tokens,
        can_manage_team=can_manage_team,
        can_view_audit_logs=can_view_audit_logs,
        invited_by=owner,
    )

    with session_factory() as db:
        project_row = db.get(Project, project.id)
        assert project_row is not None
        project_row.audit_log_visibility = "specific"
        db.commit()

    with session_factory() as db:
        access = get_project_access(project.id, current_user=member, db=db)

        assert access.role == ROLE_MEMBER
        assert access.can_push_pull_secrets is can_push_pull_secrets
        assert access.can_manage_runtime_tokens is can_manage_runtime_tokens
        assert access.can_manage_team is can_manage_team
        assert access.can_view_audit_logs is can_view_audit_logs

        _assert_guard(
            guard=require_secret_management,
            access=access,
            allowed=can_push_pull_secrets,
        )
        _assert_guard(
            guard=require_runtime_token_management,
            access=access,
            allowed=can_manage_runtime_tokens,
        )
        _assert_guard(
            guard=require_team_management,
            access=access,
            allowed=can_manage_team,
        )
        _assert_guard(
            guard=require_project_owner,
            access=access,
            allowed=False,
        )

        if can_view_audit_logs:
            assert require_audit_log_access(access, member, db) is access
        else:
            with pytest.raises(HTTPException) as audit_error:
                require_audit_log_access(access, member, db)
            assert audit_error.value.status_code == 403


def test_project_owner_is_granted_every_project_permission(session_factory, seeder) -> None:
    owner = seeder.user("owner-all-permissions@example.com")
    project = seeder.project(owner, name="owner-permissions-project")

    with session_factory() as db:
        access = get_project_access(project.id, current_user=owner, db=db)

        assert access.role == ROLE_OWNER
        assert access.can_push_pull_secrets is True
        assert access.can_manage_runtime_tokens is True
        assert access.can_manage_team is True
        assert access.can_view_audit_logs is True
        assert require_project_owner(access) is access
        assert require_secret_management(access) is access
        assert require_runtime_token_management(access) is access
        assert require_team_management(access) is access
        assert require_audit_log_access(access, owner, db) is access


def test_non_member_cannot_resolve_project_access(session_factory, seeder) -> None:
    owner = seeder.user("owner-non-member-check@example.com")
    non_member = seeder.user("non-member-check@example.com")
    project = seeder.project(owner, name="non-member-check-project")

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            get_project_access(project.id, current_user=non_member, db=db)

    assert error.value.status_code == 403
    assert error.value.detail == "You do not have access to this project."


@pytest.mark.parametrize(
    ("visibility", "member_grant", "expected_access"),
    (
        ("owner_only", False, False),
        ("owner_only", True, False),
        ("members", False, True),
        ("members", True, True),
        ("specific", False, False),
        ("specific", True, True),
    ),
)
def test_audit_visibility_controls_member_access(
    session_factory,
    seeder,
    visibility: str,
    member_grant: bool,
    expected_access: bool,
) -> None:
    owner = seeder.user("owner-audit-visibility-matrix@example.com")
    member = seeder.user("member-audit-visibility-matrix@example.com")
    project = seeder.project(owner, name="audit-visibility-matrix-project")
    seeder.add_member(
        project=project,
        user=member,
        can_view_audit_logs=member_grant,
        invited_by=owner,
    )

    with session_factory() as db:
        project_row = db.get(Project, project.id)
        assert project_row is not None
        project_row.audit_log_visibility = visibility
        db.commit()

    with session_factory() as db:
        access = get_project_access(project.id, current_user=member, db=db)
        assert access.can_view_audit_logs is expected_access

        if expected_access:
            assert require_audit_log_access(access, member, db) is access
        else:
            with pytest.raises(HTTPException) as error:
                require_audit_log_access(access, member, db)
            assert error.value.status_code == 403
