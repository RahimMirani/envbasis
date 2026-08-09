from __future__ import annotations

from fastapi import HTTPException

from app.api.deps import ProjectAccess, require_audit_log_access
from app.api.routes.audit_logs import export_audit_logs, list_audit_logs, list_unified_audit_logs
from app.api.routes.projects import list_projects
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.services.audit import write_audit_log


def _member_access(project, *, can_view_audit_logs: bool) -> ProjectAccess:
    return ProjectAccess(
        project=project,
        role="member",
        can_push_pull_secrets=False,
        can_manage_runtime_tokens=False,
        can_manage_team=False,
        can_view_audit_logs=can_view_audit_logs,
    )


def test_member_denied_audit_log_access_is_recorded(session_factory, seeder) -> None:
    owner = seeder.user("owner-audit-denied@example.com")
    member = seeder.user("member-audit-denied@example.com")
    project = seeder.project(owner, name="audit-denied-project")
    seeder.add_member(project=project, user=member, invited_by=owner)

    with session_factory() as db:
        try:
            require_audit_log_access(
                project_access=_member_access(project, can_view_audit_logs=False),
                current_user=member,
                db=db,
            )
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail == "You do not have permission to view this project's audit logs."
        else:  # pragma: no cover
            raise AssertionError("Expected member audit log access to be denied")

    assert seeder.audit_actions(project) == ["audit_logs.access_denied"]


def test_member_can_view_and_export_audit_logs_when_visibility_enabled(session_factory, seeder) -> None:
    owner = seeder.user("owner-audit-visible@example.com")
    member = seeder.user("member-audit-visible@example.com")
    project = seeder.project(owner, name="audit-visible-project")
    seeder.add_member(project=project, user=member, invited_by=owner)

    with session_factory() as db:
        project_row = db.get(Project, project.id)
        assert project_row is not None
        project_row.audit_log_visibility = "members"
        db.commit()

    with session_factory() as db:
        logs = list_audit_logs(
            project_id=project.id,
            limit=50,
            project_access=_member_access(project, can_view_audit_logs=True),
            current_user=member,
            db=db,
        )

    assert logs == []

    with session_factory() as db:
        export_response = export_audit_logs(
            project_id=project.id,
            format="json",
            project_access=_member_access(project, can_view_audit_logs=True),
            current_user=member,
            db=db,
        )

    assert export_response.media_type == "application/json"
    assert seeder.audit_actions(project) == ["audit_logs.viewed", "audit_logs.exported"]


def test_specific_audit_visibility_appears_and_disappears_with_member_grant(session_factory, seeder) -> None:
    owner = seeder.user("owner-audit-specific@example.com")
    member = seeder.user("member-audit-specific@example.com")
    project = seeder.project(owner, name="audit-specific-project")
    seeder.add_member(
        project=project,
        user=member,
        can_view_audit_logs=True,
        invited_by=owner,
    )

    with session_factory() as db:
        project_row = db.get(Project, project.id)
        assert project_row is not None
        project_row.audit_log_visibility = "specific"
        write_audit_log(
            db,
            project_id=project.id,
            user_id=owner.id,
            action="project.updated",
            metadata={"audit_log_visibility": "specific"},
        )
        db.commit()

    with session_factory() as db:
        projects = list_projects(current_user=member, db=db)
        unified = list_unified_audit_logs(
            limit=50,
            cursor=None,
            project_id=None,
            source="project",
            current_user=member,
            db=db,
        )

    listed_project = next((item for item in projects if item.id == project.id), None)
    assert listed_project is not None
    assert listed_project.can_view_audit_logs is True
    assert [log.project_id for log in unified.logs] == [project.id]

    with session_factory() as db:
        membership = db.scalar(
            db.query(ProjectMember).filter(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == member.id,
            ).statement
        )
        assert membership is not None
        membership.can_view_audit_logs = False
        db.commit()

    with session_factory() as db:
        projects = list_projects(current_user=member, db=db)
        unified = list_unified_audit_logs(
            limit=50,
            cursor=None,
            project_id=None,
            source="project",
            current_user=member,
            db=db,
        )

    listed_project = next((item for item in projects if item.id == project.id), None)
    assert listed_project is not None
    assert listed_project.can_view_audit_logs is False
    assert unified.logs == []
