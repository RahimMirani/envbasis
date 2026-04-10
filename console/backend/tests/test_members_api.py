from __future__ import annotations

from app.api.deps import ProjectAccess
from app.api.routes.projects import bulk_revoke_members, list_members
from app.schemas.member import MemberBulkRevokeRequest


def test_bulk_revoke_members_removes_multiple_members(session_factory, seeder) -> None:
    owner = seeder.user("owner-bulk-members@example.com")
    member_one = seeder.user("member-one@example.com")
    member_two = seeder.user("member-two@example.com")
    project = seeder.project(owner, name="bulk-members-project")
    seeder.add_member(project=project, user=member_one, invited_by=owner)
    seeder.add_member(project=project, user=member_two, invited_by=owner)
    access = ProjectAccess(project=project, role="owner", can_push_pull_secrets=True)

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
