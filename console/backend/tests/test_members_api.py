from __future__ import annotations

from fastapi import HTTPException

from app.api.deps import ProjectAccess
from app.api.routes.projects import (
    bulk_revoke_members,
    bulk_update_member_permissions,
    list_members,
    update_member_permissions,
)
from app.schemas.member import (
    MemberBulkPermissionUpdateRequest,
    MemberBulkRevokeRequest,
    MemberPermissionUpdateRequest,
)


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_bulk_revoke_members_removes_multiple_members(session_factory, seeder) -> None:
    owner = seeder.user("owner-bulk-members@example.com")
    member_one = seeder.user("member-one@example.com")
    member_two = seeder.user("member-two@example.com")
    project = seeder.project(owner, name="bulk-members-project")
    seeder.add_member(project=project, user=member_one, invited_by=owner)
    seeder.add_member(project=project, user=member_two, invited_by=owner)
    access = _owner_access(project)

    with session_factory() as db:
        response = bulk_revoke_members(
            payload=MemberBulkRevokeRequest(emails=[member_one.email, member_two.email]),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert response.detail == "Revoked 2 member(s)."

    with session_factory() as db:
        remaining_members = list_members(
            project_access=access,
            db=db,
        )

    assert [member.email for member in remaining_members] == [owner.email]


def test_update_member_permissions_updates_multiple_flags_and_audits(session_factory, seeder) -> None:
    owner = seeder.user("owner-permissions@example.com")
    member = seeder.user("member-permissions@example.com")
    project = seeder.project(owner, name="member-permissions-project")
    seeder.add_member(project=project, user=member, invited_by=owner)
    access = _owner_access(project)

    with session_factory() as db:
        updated = update_member_permissions(
            payload=MemberPermissionUpdateRequest(
                email=member.email,
                can_push_pull_secrets=True,
                can_manage_runtime_tokens=True,
                can_manage_team=True,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert updated.can_push_pull_secrets is True
    assert updated.can_manage_runtime_tokens is True
    assert updated.can_manage_team is True
    assert seeder.audit_actions(project)[-1] == "member.permissions.updated"


def test_bulk_update_member_permissions_updates_selected_members_and_audits(session_factory, seeder) -> None:
    owner = seeder.user("owner-bulk-permissions@example.com")
    member_one = seeder.user("member-bulk-one@example.com")
    member_two = seeder.user("member-bulk-two@example.com")
    project = seeder.project(owner, name="bulk-permissions-project")
    seeder.add_member(project=project, user=member_one, invited_by=owner)
    seeder.add_member(project=project, user=member_two, invited_by=owner)
    access = _owner_access(project)

    with session_factory() as db:
        updated_members = bulk_update_member_permissions(
            payload=MemberBulkPermissionUpdateRequest(
                emails=[member_one.email, member_two.email],
                can_manage_runtime_tokens=True,
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )

    assert {member.email for member in updated_members} == {member_one.email, member_two.email}
    assert all(member.can_manage_runtime_tokens for member in updated_members)
    assert seeder.audit_actions(project)[-1] == "members.permissions.bulk_updated"


def test_member_permission_update_rejects_owner_target(session_factory, seeder) -> None:
    owner = seeder.user("owner-target@example.com")
    project = seeder.project(owner, name="owner-target-project")
    access = _owner_access(project)

    with session_factory() as db:
        try:
            update_member_permissions(
                payload=MemberPermissionUpdateRequest(
                    email=owner.email,
                    can_manage_team=False,
                ),
                project_access=access,
                current_user=owner,
                db=db,
            )
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == "Project owner permissions cannot be changed."
        else:  # pragma: no cover
            raise AssertionError("Expected owner permission update to be rejected")
