from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app.api.deps import ProjectAccess
from app.api.routes.projects import (
    bulk_revoke_members,
    bulk_update_member_permissions,
    invite_member,
    list_members,
    update_member_permissions,
)
from app.models.project_invitation import ProjectInvitation
from app.models.project_member import ProjectMember
from app.schemas.member import (
    MemberBulkPermissionUpdateRequest,
    MemberBulkRevokeRequest,
    MemberInviteRequest,
    MemberPermissionUpdateRequest,
)
from app.services.invitation_service import accept_invitation


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def _member_access(
    project,
    *,
    can_push_pull_secrets: bool = False,
    can_manage_runtime_tokens: bool = False,
    can_manage_team: bool = True,
    can_view_audit_logs: bool = False,
) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="member",
        can_push_pull_secrets=can_push_pull_secrets,
        can_manage_runtime_tokens=can_manage_runtime_tokens,
        can_manage_team=can_manage_team,
        can_view_audit_logs=can_view_audit_logs,
    )


@pytest.mark.parametrize(
    "permission",
    (
        "can_push_pull_secrets",
        "can_manage_runtime_tokens",
        "can_view_audit_logs",
    ),
)
def test_team_manager_cannot_grant_a_permission_they_do_not_have(
    session_factory,
    seeder,
    permission: str,
) -> None:
    owner = seeder.user("owner-delegation-denied@example.com")
    manager = seeder.user("manager-delegation-denied@example.com")
    target = seeder.user("target-delegation-denied@example.com")
    project = seeder.project(owner, name="delegation-denied-project")
    seeder.add_member(project=project, user=manager, can_manage_team=True, invited_by=owner)
    seeder.add_member(project=project, user=target, invited_by=owner)

    payload = MemberPermissionUpdateRequest(
        email=target.email,
        **{permission: True},
    )
    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            update_member_permissions(
                payload=payload,
                project_access=_member_access(project),
                current_user=manager,
                db=db,
            )

    assert error.value.status_code == 403
    assert permission in str(error.value.detail)

    with session_factory() as db:
        membership = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == target.id,
            )
        )
        assert membership is not None
        assert getattr(membership, permission) is False


def test_team_manager_cannot_escalate_their_own_permissions(session_factory, seeder) -> None:
    owner = seeder.user("owner-self-escalation@example.com")
    manager = seeder.user("manager-self-escalation@example.com")
    project = seeder.project(owner, name="self-escalation-project")
    seeder.add_member(project=project, user=manager, can_manage_team=True, invited_by=owner)

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            update_member_permissions(
                payload=MemberPermissionUpdateRequest(
                    email=manager.email,
                    can_push_pull_secrets=True,
                ),
                project_access=_member_access(project),
                current_user=manager,
                db=db,
            )

    assert error.value.status_code == 403


def test_team_manager_cannot_bypass_delegation_guard_with_bulk_update(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-bulk-escalation@example.com")
    manager = seeder.user("manager-bulk-escalation@example.com")
    target_one = seeder.user("target-one-bulk-escalation@example.com")
    target_two = seeder.user("target-two-bulk-escalation@example.com")
    project = seeder.project(owner, name="bulk-escalation-project")
    seeder.add_member(project=project, user=manager, can_manage_team=True, invited_by=owner)
    seeder.add_member(project=project, user=target_one, invited_by=owner)
    seeder.add_member(project=project, user=target_two, invited_by=owner)

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            bulk_update_member_permissions(
                payload=MemberBulkPermissionUpdateRequest(
                    emails=[target_one.email, target_two.email],
                    can_manage_runtime_tokens=True,
                ),
                project_access=_member_access(project),
                current_user=manager,
                db=db,
            )

    assert error.value.status_code == 403

    with session_factory() as db:
        memberships = db.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id.in_((target_one.id, target_two.id)),
            )
        ).all()
        assert len(memberships) == 2
        assert all(member.can_manage_runtime_tokens is False for member in memberships)


def test_team_manager_cannot_invite_with_permissions_they_do_not_have(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-invite-escalation@example.com")
    manager = seeder.user("manager-invite-escalation@example.com")
    project = seeder.project(owner, name="invite-escalation-project")
    seeder.add_member(project=project, user=manager, can_manage_team=True, invited_by=owner)

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            invite_member(
                payload=MemberInviteRequest(
                    email="new-member-escalation@example.com",
                    can_view_audit_logs=True,
                ),
                project_access=_member_access(project),
                current_user=manager,
                db=db,
            )

    assert error.value.status_code == 403

    with session_factory() as db:
        invitations = db.scalars(
            select(ProjectInvitation).where(ProjectInvitation.project_id == project.id)
        ).all()
        assert invitations == []


def test_legacy_invitation_cannot_grant_more_than_the_inviter_currently_has(
    session_factory,
    seeder,
) -> None:
    owner = seeder.user("owner-legacy-invite@example.com")
    manager = seeder.user("manager-legacy-invite@example.com")
    invitee = seeder.user("invitee-legacy-invite@example.com")
    project = seeder.project(owner, name="legacy-invite-project")
    seeder.add_member(project=project, user=manager, can_manage_team=True, invited_by=owner)

    with session_factory() as db:
        invitation = ProjectInvitation(
            project_id=project.id,
            email=invitee.email,
            email_normalized=invitee.email,
            role="member",
            can_push_pull_secrets=True,
            can_manage_runtime_tokens=False,
            can_manage_team=False,
            can_view_audit_logs=False,
            invited_by_user_id=manager.id,
            status="pending",
            invite_token_hash="a" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            send_count=1,
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        invitation_id = invitation.id

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            accept_invitation(db, user=invitee, invitation_id=invitation_id)

    assert error.value.status_code == 409

    with session_factory() as db:
        stored_invitation = db.get(ProjectInvitation, invitation_id)
        membership = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invitee.id,
            )
        )
        assert stored_invitation is not None
        assert stored_invitation.status == "revoked"
        assert membership is None


def test_invitation_cannot_create_an_owner_role(session_factory, seeder) -> None:
    owner = seeder.user("owner-role-invite@example.com")
    invitee = seeder.user("invitee-role-invite@example.com")
    project = seeder.project(owner, name="role-invite-project")

    with session_factory() as db:
        invitation = ProjectInvitation(
            project_id=project.id,
            email=invitee.email,
            email_normalized=invitee.email,
            role="owner",
            can_push_pull_secrets=True,
            can_manage_runtime_tokens=True,
            can_manage_team=True,
            can_view_audit_logs=True,
            invited_by_user_id=owner.id,
            status="pending",
            invite_token_hash="b" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            send_count=1,
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        invitation_id = invitation.id

    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            accept_invitation(db, user=invitee, invitation_id=invitation_id)

    assert error.value.status_code == 409

    with session_factory() as db:
        membership = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == invitee.id,
            )
        )
        assert membership is None


def test_team_manager_can_delegate_a_permission_they_have(session_factory, seeder) -> None:
    owner = seeder.user("owner-delegation-allowed@example.com")
    manager = seeder.user("manager-delegation-allowed@example.com")
    target = seeder.user("target-delegation-allowed@example.com")
    project = seeder.project(owner, name="delegation-allowed-project")
    seeder.add_member(
        project=project,
        user=manager,
        can_push_pull_secrets=True,
        can_manage_team=True,
        invited_by=owner,
    )
    seeder.add_member(project=project, user=target, invited_by=owner)

    with session_factory() as db:
        updated = update_member_permissions(
            payload=MemberPermissionUpdateRequest(
                email=target.email,
                can_push_pull_secrets=True,
            ),
            project_access=_member_access(project, can_push_pull_secrets=True),
            current_user=manager,
            db=db,
        )

    assert updated.can_push_pull_secrets is True


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
