from __future__ import annotations

from app.api.deps import ProjectAccess
from app.api.routes.access_control import (
    create_access_role,
    create_organization,
    create_role_assignment,
    list_access_roles,
    simulate_permission,
)
from app.models.access_role import AccessRole, AccessRoleAssignment, AccessRolePermission
from app.models.organization import Organization
from app.schemas.access_control import (
    AccessRoleCreate,
    OrganizationCreate,
    PermissionSimulationRequest,
    RoleAssignmentCreate,
    RolePermissionInput,
)
from app.services.access_control import evaluate_permission


def _owner_access(project) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="owner",
        can_push_pull_secrets=True,
        can_manage_runtime_tokens=True,
        can_manage_team=True,
        can_view_audit_logs=True,
    )


def test_builtin_and_custom_roles_with_scoped_simulation(session_factory, seeder) -> None:
    owner = seeder.user("rbac-owner@example.com")
    member = seeder.user("rbac-member@example.com")
    project = seeder.project(owner, name="rbac-project")
    production = seeder.environment(project, name="production")
    development = seeder.environment(project, name="development")
    access = _owner_access(project)

    with session_factory() as db:
        roles = list_access_roles(project_access=access, db=db)
        role = create_access_role(
            payload=AccessRoleCreate(
                name="payments-reader",
                permissions=[
                    RolePermissionInput(
                        resource="secrets",
                        action="read",
                        environment_id=production.id,
                        path="/payments",
                        recursive=True,
                    )
                ],
            ),
            project_access=access,
            current_user=owner,
            db=db,
        )
        create_role_assignment(
            payload=RoleAssignmentCreate(role_id=role.id, user_id=member.id),
            project_access=access,
            current_user=owner,
            db=db,
        )
        allowed = simulate_permission(
            payload=PermissionSimulationRequest(
                user_id=member.id,
                resource="secrets",
                action="read",
                environment_id=production.id,
                path="/payments/stripe",
            ),
            project_access=access,
            db=db,
        )
        wrong_environment = simulate_permission(
            payload=PermissionSimulationRequest(
                user_id=member.id,
                resource="secrets",
                action="read",
                environment_id=development.id,
                path="/payments",
            ),
            project_access=access,
            db=db,
        )

    assert {item.name for item in roles} == {"admin", "member", "viewer", "no-access"}
    assert allowed.allowed is True
    assert wrong_environment.allowed is False


def test_simulation_mirrors_default_access_when_no_roles_assigned(session_factory, seeder) -> None:
    owner = seeder.user("sim-owner@example.com")
    reader = seeder.user("sim-reader@example.com")
    writer = seeder.user("sim-writer@example.com")
    outsider = seeder.user("sim-outsider@example.com")
    project = seeder.project(owner, name="sim-project")
    access = _owner_access(project)
    seeder.add_member(project=project, user=reader, can_push_pull_secrets=False)
    seeder.add_member(project=project, user=writer, can_push_pull_secrets=True)

    def simulate(db, user_id, action):
        return simulate_permission(
            payload=PermissionSimulationRequest(
                user_id=user_id, resource="secrets", action=action, path="/"
            ),
            project_access=access,
            db=db,
        )

    with session_factory() as db:
        owner_write = simulate(db, owner.id, "write")
        reader_read = simulate(db, reader.id, "read")
        reader_write = simulate(db, reader.id, "write")
        writer_write = simulate(db, writer.id, "write")
        outsider_read = simulate(db, outsider.id, "read")

    assert owner_write.allowed is True and owner_write.reason == "project_owner"
    assert reader_read.allowed is True and reader_read.reason == "member_default_read"
    assert reader_write.allowed is False and reader_write.reason == "member_write_not_allowed"
    assert writer_write.allowed is True and writer_write.reason == "member_can_push_pull"
    assert outsider_read.allowed is False and outsider_read.reason == "not_a_project_member"


def test_roles_are_additive_but_explicit_deny_wins_for_users_and_machines(
    session_factory, seeder
) -> None:
    owner = seeder.user("rbac-conflict-owner@example.com")
    member = seeder.user("rbac-conflict-member@example.com")
    project = seeder.project(owner, name="rbac-conflict")
    environment = seeder.environment(project, name="prod")

    with session_factory() as db:
        allow_read = AccessRole(project_id=project.id, name="read", is_builtin=False)
        allow_write = AccessRole(project_id=project.id, name="write", is_builtin=False)
        deny_private = AccessRole(project_id=project.id, name="deny-private", is_builtin=False)
        db.add_all([allow_read, allow_write, deny_private])
        db.flush()
        db.add_all(
            [
                AccessRolePermission(role_id=allow_read.id, resource="secrets", action="read", effect="allow", path="/", recursive=True),
                AccessRolePermission(role_id=allow_write.id, resource="secrets", action="write", effect="allow", path="/payments", recursive=True),
                AccessRolePermission(role_id=deny_private.id, resource="secrets", action="read", effect="deny", path="/payments/private", recursive=True),
                AccessRoleAssignment(role_id=allow_read.id, user_id=member.id),
                AccessRoleAssignment(role_id=allow_write.id, user_id=member.id),
                AccessRoleAssignment(role_id=deny_private.id, user_id=member.id),
            ]
        )
        db.commit()
        public_read = evaluate_permission(db, project=project, user_id=member.id, resource="secrets", action="read", environment_id=environment.id, path="/payments/public")
        write = evaluate_permission(db, project=project, user_id=member.id, resource="secrets", action="write", environment_id=environment.id, path="/payments")
        private_read = evaluate_permission(db, project=project, user_id=member.id, resource="secrets", action="read", environment_id=environment.id, path="/payments/private/card")

    assert public_read.allowed is True
    assert write.allowed is True
    assert private_read.allowed is False
    assert private_read.reason == "explicit_deny"


def test_organization_role_applies_to_attached_project(session_factory, seeder) -> None:
    owner = seeder.user("org-owner@example.com")
    member = seeder.user("org-member@example.com")
    project = seeder.project(owner, name="org-project")
    with session_factory() as db:
        organization_read = create_organization(
            payload=OrganizationCreate(name="Acme"), current_user=owner, db=db
        )
        project_row = db.get(type(project), project.id)
        project_row.organization_id = organization_read.id
        role = AccessRole(organization_id=organization_read.id, name="org-reader", is_builtin=False)
        db.add(role)
        db.flush()
        db.add_all(
            [
                AccessRolePermission(role_id=role.id, resource="secrets", action="list", effect="allow", recursive=True),
                AccessRoleAssignment(role_id=role.id, user_id=member.id),
            ]
        )
        db.commit()
        decision = evaluate_permission(db, project=project_row, user_id=member.id, resource="secrets", action="list")

    assert decision.allowed is True
