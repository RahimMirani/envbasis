from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.audit as audit_service
from app.core.config import settings
from app.core.middleware import rate_limiter
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.runtime_token import RuntimeToken
from app.models.secret import Secret
from app.models.user import User


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    settings.secrets_master_key = Fernet.generate_key().decode("utf-8")
    audit_service._last_cleanup_at = None
    rate_limiter._windows.clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )

    Base.metadata.create_all(engine)

    try:
        yield test_session_factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@dataclass
class Seeder:
    session_factory: sessionmaker[Session]

    def user(self, email: str) -> User:
        with self.session_factory() as db:
            user = User(email=email)
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    def project(self, owner: User, *, name: str = "envbasis") -> Project:
        with self.session_factory() as db:
            project = Project(
                name=name,
                description="Test project",
                owner_id=owner.id,
                audit_log_visibility="owner_only",
            )
            db.add(project)
            db.flush()
            db.add(
                ProjectMember(
                    project_id=project.id,
                    user_id=owner.id,
                    role="owner",
                    can_push_pull_secrets=True,
                    can_manage_runtime_tokens=True,
                    can_manage_team=True,
                    invited_by=owner.id,
                )
            )
            db.commit()
            db.refresh(project)
            return project

    def environment(self, project: Project, *, name: str = "dev") -> Environment:
        with self.session_factory() as db:
            environment = Environment(project_id=project.id, name=name)
            db.add(environment)
            db.commit()
            db.refresh(environment)
            return environment

    def add_member(
        self,
        *,
        project: Project,
        user: User,
        can_push_pull_secrets: bool = False,
        can_manage_runtime_tokens: bool = False,
        can_manage_team: bool = False,
        can_view_audit_logs: bool = False,
        invited_by: User | None = None,
    ) -> ProjectMember:
        with self.session_factory() as db:
            member = ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role="member",
                can_push_pull_secrets=can_push_pull_secrets,
                can_manage_runtime_tokens=can_manage_runtime_tokens,
                can_manage_team=can_manage_team,
                can_view_audit_logs=can_view_audit_logs,
                invited_by=invited_by.id if invited_by is not None else None,
            )
            db.add(member)
            db.commit()
            db.refresh(member)
            return member

    def secret_versions(self, environment: Environment) -> list[Secret]:
        with self.session_factory() as db:
            return list(
                db.scalars(
                    select(Secret)
                    .where(Secret.environment_id == environment.id)
                    .order_by(Secret.key.asc(), Secret.version.asc())
                ).all()
            )

    def runtime_token(self, token_id: str | uuid.UUID) -> RuntimeToken | None:
        with self.session_factory() as db:
            return db.get(RuntimeToken, token_id)

    def audit_actions(self, project: Project) -> list[str]:
        with self.session_factory() as db:
            return list(
                db.scalars(
                    select(AuditLog.action)
                    .where(AuditLog.project_id == project.id)
                    .order_by(AuditLog.created_at.asc())
                ).all()
            )


@pytest.fixture
def seeder(session_factory: sessionmaker[Session]) -> Seeder:
    return Seeder(session_factory=session_factory)
