from __future__ import annotations

from fastapi import HTTPException
import pytest

from app.api.deps import ProjectAccess
from app.api.routes.approvals import (
    act_on_approval_request,
    create_approval_policy,
    create_approval_request,
)
from app.api.routes.secrets import create_secret, delete_secret, reveal_secret
from app.schemas.approval import ApprovalAction, ApprovalPolicyCreate, ApprovalStep, SecretChangeProposal
from app.schemas.secret import SecretCreateRequest
from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission


def _access(project, user, *, owner: bool = False) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner" if owner else "member",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=owner,
        can_manage_team=owner,
        can_view_audit_logs=owner,
        subject_user_id=user.id,
    )


def test_two_step_approval_gates_and_applies_encrypted_secret_change(session_factory, seeder) -> None:
    owner = seeder.user("approval-owner@example.com")
    author = seeder.user("approval-author@example.com")
    security = seeder.user("approval-security@example.com")
    production = seeder.user("approval-production@example.com")
    project = seeder.project(owner, name="approval-project")
    environment = seeder.environment(project, name="production")
    owner_access = _access(project, owner, owner=True)
    author_access = _access(project, author)
    security_access = _access(project, security)
    production_access = _access(project, production)

    with session_factory() as db:
        policy = create_approval_policy(
            payload=ApprovalPolicyCreate(
                name="Production changes",
                environment_id=environment.id,
                path="/payments",
                actions=["create", "update", "delete"],
                steps=[
                    ApprovalStep(name="Security", approver_user_ids=[security.id]),
                    ApprovalStep(name="Production", approver_user_ids=[production.id]),
                ],
                prevent_self_approval=True,
            ),
            project_access=owner_access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db, pytest.raises(HTTPException) as gated:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="STRIPE_KEY", value="sk_pending", path="/payments"),
            project_access=author_access,
            current_user=author,
            db=db,
        )
    assert gated.value.status_code == 409
    assert gated.value.detail["code"] == "approval_required"

    with session_factory() as db:
        request = create_approval_request(
            payload=SecretChangeProposal(
                environment_id=environment.id,
                path="/payments",
                secret_key="STRIPE_KEY",
                operation="create",
                value="sk_approved",
                metadata={"tags": ["production"], "service": "billing"},
                comment="Ready for production",
            ),
            project_access=author_access,
            current_user=author,
            db=db,
        )
    assert request.policy_id == policy.id
    assert request.status == "pending"
    assert request.total_steps == 2

    with session_factory() as db, pytest.raises(HTTPException) as unauthorized:
        act_on_approval_request(
            request_id=request.id,
            payload=ApprovalAction(action="approve"),
            project_access=author_access,
            current_user=author,
            db=db,
        )
    assert unauthorized.value.status_code == 403

    with session_factory() as db:
        first = act_on_approval_request(
            request_id=request.id,
            payload=ApprovalAction(action="approve", comment="Security approved"),
            project_access=security_access,
            current_user=security,
            db=db,
        )
    assert first.status == "pending"
    assert first.current_step == 1

    with session_factory() as db:
        final = act_on_approval_request(
            request_id=request.id,
            payload=ApprovalAction(action="approve", comment="Production approved"),
            project_access=production_access,
            current_user=production,
            db=db,
        )
    assert final.status == "approved"
    assert [event.action for event in final.events] == ["created", "approved", "approved"]

    with session_factory() as db:
        revealed = reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="STRIPE_KEY",
            path="/payments",
            project_access=owner_access,
            current_user=owner,
            db=db,
        )
    assert revealed.value == "sk_approved"
    assert revealed.tags == ["production"]
    assert revealed.service == "billing"


def test_role_approvers_comment_reject_cancel_and_self_approval_guard(session_factory, seeder) -> None:
    owner = seeder.user("approval-actions-owner@example.com")
    author = seeder.user("approval-actions-author@example.com")
    reviewer = seeder.user("approval-actions-reviewer@example.com")
    project = seeder.project(owner, name="approval-actions")
    environment = seeder.environment(project, name="production")
    owner_access = _access(project, owner, owner=True)
    author_access = _access(project, author)
    reviewer_access = _access(project, reviewer)

    with session_factory() as db:
        role = AccessRole(project_id=project.id, name="reviewer", is_builtin=False)
        db.add(role)
        db.flush()
        db.add_all([
            AccessRolePermission(role_id=role.id, resource="secrets", action="write", effect="allow", recursive=True),
            AccessRoleAssignment(role_id=role.id, user_id=reviewer.id),
        ])
        db.commit()
        policy = create_approval_policy(
            payload=ApprovalPolicyCreate(
                name="Role approval",
                environment_id=environment.id,
                actions=["create"],
                steps=[ApprovalStep(name="Reviewers", approver_role_ids=[role.id])],
            ),
            project_access=owner_access,
            current_user=owner,
            db=db,
        )

    def submit(key: str):
        with session_factory() as db:
            return create_approval_request(
                payload=SecretChangeProposal(environment_id=environment.id, secret_key=key, operation="create", value="pending"),
                project_access=author_access,
                current_user=author,
                db=db,
            )

    rejected = submit("REJECT_ME")
    with session_factory() as db:
        commented = act_on_approval_request(request_id=rejected.id, payload=ApprovalAction(action="comment", comment="Needs work"), project_access=reviewer_access, current_user=reviewer, db=db)
        rejected_result = act_on_approval_request(request_id=rejected.id, payload=ApprovalAction(action="reject", comment="Unsafe"), project_access=reviewer_access, current_user=reviewer, db=db)
    assert commented.events[-1].action == "comment"
    assert rejected_result.status == "rejected"

    cancelled = submit("CANCEL_ME")
    with session_factory() as db:
        cancelled_result = act_on_approval_request(request_id=cancelled.id, payload=ApprovalAction(action="cancel"), project_access=author_access, current_user=author, db=db)
    assert cancelled_result.status == "cancelled"

    self_request = submit("SELF_APPROVAL")
    with session_factory() as db:
        db.add(AccessRoleAssignment(role_id=role.id, user_id=author.id))
        db.commit()
        with pytest.raises(HTTPException) as self_denied:
            act_on_approval_request(request_id=self_request.id, payload=ApprovalAction(action="approve"), project_access=author_access, current_user=author, db=db)
    assert self_denied.value.status_code == 403
    assert "own changes" in self_denied.value.detail
    assert policy.prevent_self_approval is True


def test_approved_delete_removes_secret_rows_and_writes_audit(session_factory, seeder) -> None:
    owner = seeder.user("approval-delete-owner@example.com")
    author = seeder.user("approval-delete-author@example.com")
    approver = seeder.user("approval-delete-approver@example.com")
    project = seeder.project(owner, name="approval-delete-project")
    environment = seeder.environment(project, name="production")
    owner_access = _access(project, owner, owner=True)
    author_access = _access(project, author)
    approver_access = _access(project, approver)

    with session_factory() as db:
        create_secret(
            project_id=project.id,
            environment_id=environment.id,
            payload=SecretCreateRequest(key="STRIPE_KEY", value="sk_live", path="/payments"),
            project_access=owner_access,
            current_user=owner,
            db=db,
        )
        create_approval_policy(
            payload=ApprovalPolicyCreate(
                name="Delete gate",
                environment_id=environment.id,
                path="/payments",
                actions=["delete"],
                steps=[ApprovalStep(name="Security", approver_user_ids=[approver.id])],
            ),
            project_access=owner_access,
            current_user=owner,
            db=db,
        )

    with session_factory() as db, pytest.raises(HTTPException) as gated:
        delete_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="STRIPE_KEY",
            path="/payments",
            project_access=author_access,
            current_user=author,
            db=db,
        )
    assert gated.value.status_code == 409

    with session_factory() as db:
        request = create_approval_request(
            payload=SecretChangeProposal(
                environment_id=environment.id,
                path="/payments",
                secret_key="STRIPE_KEY",
                operation="delete",
            ),
            project_access=author_access,
            current_user=author,
            db=db,
        )
        approved = act_on_approval_request(
            request_id=request.id,
            payload=ApprovalAction(action="approve"),
            project_access=approver_access,
            current_user=approver,
            db=db,
        )

    assert approved.status == "approved"
    assert seeder.secret_versions(environment) == []
    deleted_logs = [entry for entry in seeder.audit_logs(project) if entry.action == "secret.deleted"]
    assert len(deleted_logs) == 1
    assert deleted_logs[0].metadata_json == {
        "key": "STRIPE_KEY",
        "path": "/payments",
        "version": 1,
        "versions_removed": 1,
        "via": "approval",
    }

    with session_factory() as db, pytest.raises(HTTPException) as missing:
        reveal_secret(
            project_id=project.id,
            environment_id=environment.id,
            secret_key="STRIPE_KEY",
            path="/payments",
            project_access=owner_access,
            current_user=owner,
            db=db,
        )
    assert missing.value.status_code == 404
