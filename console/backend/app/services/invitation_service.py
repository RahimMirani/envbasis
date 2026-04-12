from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.project import Project
from app.models.project_invitation import ProjectInvitation
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.invitation import (
    InvitationDetail,
    InvitationSummary,
    InviteMemberResponse,
    ProjectInvitationRead,
)
from app.schemas.member import ProjectMemberRead
from app.services.audit import write_audit_log
from app.services.invite_email import send_project_invite_email

INVITE_EXPIRY_DAYS = 15
INVITE_COOLDOWN_DAYS = 5
MAX_SENDS_PER_COOLDOWN_CYCLE = 2


def normalize_invite_email(email: str) -> str:
    return email.strip().lower()


def hash_invite_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def apply_cooldown_reset(invitation: ProjectInvitation) -> None:
    now = utcnow()
    if (
        invitation.send_count >= MAX_SENDS_PER_COOLDOWN_CYCLE
        and invitation.cooldown_until is not None
        and now >= invitation.cooldown_until
    ):
        invitation.send_count = 0
        invitation.cooldown_until = None


def assert_can_send(invitation: ProjectInvitation) -> None:
    apply_cooldown_reset(invitation)
    now = utcnow()
    if (
        invitation.send_count >= MAX_SENDS_PER_COOLDOWN_CYCLE
        and invitation.cooldown_until is not None
        and now < invitation.cooldown_until
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "invitation_cooldown_active",
                "message": (
                    "This project has already sent the maximum number of invite emails to this address. "
                    f"Try again after {invitation.cooldown_until.isoformat()}."
                ),
                "cooldown_until": invitation.cooldown_until.isoformat(),
            },
        )


def mark_expired_pending(db: Session, invitation: ProjectInvitation) -> None:
    if invitation.status != "pending":
        return
    if invitation.expires_at > utcnow():
        return
    invitation.status = "expired"
    write_audit_log(
        db,
        project_id=invitation.project_id,
        user_id=None,
        action="invitation.expired",
        metadata={
            "invitation_id": str(invitation.id),
            "email": invitation.email_normalized,
        },
    )


def invitation_to_read(
    db: Session,
    invitation: ProjectInvitation,
    project_name: str,
) -> ProjectInvitationRead:
    inviter_email = None
    if invitation.invited_by_user_id:
        inviter = db.get(User, invitation.invited_by_user_id)
        if inviter:
            inviter_email = inviter.email
    return ProjectInvitationRead(
        id=invitation.id,
        project_id=invitation.project_id,
        project_name=project_name,
        email=invitation.email,
        role=invitation.role,
        can_push_pull_secrets=invitation.can_push_pull_secrets,
        can_manage_runtime_tokens=invitation.can_manage_runtime_tokens,
        can_manage_team=invitation.can_manage_team,
        can_view_audit_logs=invitation.can_view_audit_logs,
        invited_by_email=inviter_email,
        status=invitation.status,
        expires_at=invitation.expires_at,
        last_sent_at=invitation.last_sent_at,
        send_count=invitation.send_count,
        cooldown_until=invitation.cooldown_until,
        created_at=invitation.created_at,
    )


def build_invite_url(raw_token: str) -> str:
    base = settings.invite_app_base_url.rstrip("/")
    return f"{base}/?invite={raw_token}"


def record_send_and_maybe_cooldown(invitation: ProjectInvitation) -> None:
    now = utcnow()
    invitation.send_count += 1
    invitation.last_sent_at = now
    if invitation.send_count >= MAX_SENDS_PER_COOLDOWN_CYCLE:
        invitation.cooldown_until = now + timedelta(days=INVITE_COOLDOWN_DAYS)


def create_or_resend_invitation(
    db: Session,
    *,
    project: Project,
    invited_email: str,
    role: str,
    can_push_pull_secrets: bool,
    can_manage_runtime_tokens: bool,
    can_manage_team: bool,
    can_view_audit_logs: bool,
    invited_by: User,
) -> InviteMemberResponse:
    normalized = normalize_invite_email(invited_email)

    if normalized == (invited_by.email or "").strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot invite yourself.",
        )

    owner = db.get(User, project.owner_id)
    if owner and normalized == owner.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project owner is already part of this project.",
        )

    existing_member = db.scalar(
        select(ProjectMember).join(User, User.id == ProjectMember.user_id).where(
            ProjectMember.project_id == project.id,
            User.email == normalized,
        )
    )
    if existing_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a project member.",
        )

    pending = db.scalar(
        select(ProjectInvitation).where(
            ProjectInvitation.project_id == project.id,
            ProjectInvitation.email_normalized == normalized,
            ProjectInvitation.status == "pending",
        )
    )

    plain_token: str | None = None

    if pending is not None:
        mark_expired_pending(db, pending)

    if pending is not None and pending.status == "pending":
        assert_can_send(pending)
        pending.role = role
        pending.can_push_pull_secrets = can_push_pull_secrets
        pending.can_manage_runtime_tokens = can_manage_runtime_tokens
        pending.can_manage_team = can_manage_team
        pending.can_view_audit_logs = can_view_audit_logs
        pending.invited_by_user_id = invited_by.id
        if pending.expires_at <= utcnow():
            pending.expires_at = utcnow() + timedelta(days=INVITE_EXPIRY_DAYS)
        plain_token = new_invite_token()
        pending.invite_token_hash = hash_invite_token(plain_token)
        record_send_and_maybe_cooldown(pending)
        write_audit_log(
            db,
            project_id=project.id,
            user_id=invited_by.id,
            action="invitation.resent",
            metadata={
                "invitation_id": str(pending.id),
                "email": normalized,
                "send_count": pending.send_count,
            },
        )
        invitation_row = pending
    else:
        plain_token = new_invite_token()
        token_hash = hash_invite_token(plain_token)
        now = utcnow()
        invitation_row = ProjectInvitation(
            project_id=project.id,
            email=invited_email.strip(),
            email_normalized=normalized,
            role=role,
            can_push_pull_secrets=can_push_pull_secrets,
            can_manage_runtime_tokens=can_manage_runtime_tokens,
            can_manage_team=can_manage_team,
            can_view_audit_logs=can_view_audit_logs,
            invited_by_user_id=invited_by.id,
            status="pending",
            invite_token_hash=token_hash,
            expires_at=now + timedelta(days=INVITE_EXPIRY_DAYS),
            send_count=0,
        )
        db.add(invitation_row)
        db.flush()
        record_send_and_maybe_cooldown(invitation_row)
        write_audit_log(
            db,
            project_id=project.id,
            user_id=invited_by.id,
            action="invitation.created",
            metadata={
                "invitation_id": str(invitation_row.id),
                "email": normalized,
                "role": role,
                "can_push_pull_secrets": can_push_pull_secrets,
                "can_manage_runtime_tokens": can_manage_runtime_tokens,
                "can_manage_team": can_manage_team,
                "can_view_audit_logs": can_view_audit_logs,
            },
        )

    invite_url = build_invite_url(plain_token) if plain_token else ""
    email_sent = send_project_invite_email(
        to_email=invitation_row.email,
        invite_url=invite_url,
        project_name=project.name,
        inviter_email=invited_by.email,
    )

    db.commit()
    db.refresh(invitation_row)

    read = invitation_to_read(db, invitation_row, project.name)
    msg = None
    if not email_sent:
        msg = (
            "Invitation saved, but email was not sent (configure INVITE_SMTP_HOST or check logs for the invite link)."
        )
    return InviteMemberResponse(invitation=read, email_sent=email_sent, message=msg)


def list_project_invitations(
    db: Session,
    *,
    project: Project,
) -> list[ProjectInvitationRead]:
    now = utcnow()
    rows = db.scalars(
        select(ProjectInvitation)
        .where(
            ProjectInvitation.project_id == project.id,
            ProjectInvitation.status == "pending",
            ProjectInvitation.expires_at > now,
        )
        .order_by(ProjectInvitation.created_at.desc())
    ).all()
    return [invitation_to_read(db, row, project.name) for row in rows]


def revoke_project_invitation(
    db: Session,
    *,
    project: Project,
    invitation_id: uuid.UUID,
    revoked_by: User,
) -> None:
    inv = db.get(ProjectInvitation, invitation_id)
    if inv is None or inv.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    if inv.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending invitations can be revoked.",
        )
    inv.status = "revoked"
    write_audit_log(
        db,
        project_id=project.id,
        user_id=revoked_by.id,
        action="invitation.revoked",
        metadata={"invitation_id": str(inv.id), "email": inv.email_normalized},
    )
    db.commit()


def list_invitations_for_user(db: Session, *, user: User) -> list[InvitationSummary]:
    normalized = normalize_invite_email(user.email)
    now = utcnow()
    rows = db.execute(
        select(ProjectInvitation, Project)
        .join(Project, Project.id == ProjectInvitation.project_id)
        .where(
            ProjectInvitation.email_normalized == normalized,
            ProjectInvitation.status == "pending",
            ProjectInvitation.expires_at > now,
        )
        .order_by(ProjectInvitation.created_at.desc())
    ).all()
    out: list[InvitationSummary] = []
    for invitation, project in rows:
        inviter_email = None
        if invitation.invited_by_user_id:
            inviter = db.get(User, invitation.invited_by_user_id)
            if inviter:
                inviter_email = inviter.email
        out.append(
            InvitationSummary(
                id=invitation.id,
                project_id=invitation.project_id,
                project_name=project.name,
                inviter_email=inviter_email,
                email=invitation.email,
                role=invitation.role,
                can_push_pull_secrets=invitation.can_push_pull_secrets,
                can_manage_runtime_tokens=invitation.can_manage_runtime_tokens,
                can_manage_team=invitation.can_manage_team,
                can_view_audit_logs=invitation.can_view_audit_logs,
                expires_at=invitation.expires_at,
                created_at=invitation.created_at,
            )
        )
    return out


def get_invitation_by_token_for_user(
    db: Session,
    *,
    user: User,
    raw_token: str,
) -> InvitationDetail:
    token_hash = hash_invite_token(raw_token)
    row = db.execute(
        select(ProjectInvitation, Project)
        .join(Project, Project.id == ProjectInvitation.project_id)
        .where(ProjectInvitation.invite_token_hash == token_hash)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    invitation, project = row
    mark_expired_pending(db, invitation)
    db.commit()
    db.refresh(invitation)
    if invitation.status == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation has expired.")
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation is no longer active.",
        )
    if normalize_invite_email(user.email) != invitation.email_normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signed-in user does not match this invitation.",
        )
    inviter_email = None
    if invitation.invited_by_user_id:
        inviter = db.get(User, invitation.invited_by_user_id)
        if inviter:
            inviter_email = inviter.email
    return InvitationDetail(
        id=invitation.id,
        project_id=invitation.project_id,
        project_name=project.name,
        inviter_email=inviter_email,
        email=invitation.email,
        role=invitation.role,
        can_push_pull_secrets=invitation.can_push_pull_secrets,
        can_manage_runtime_tokens=invitation.can_manage_runtime_tokens,
        can_manage_team=invitation.can_manage_team,
        can_view_audit_logs=invitation.can_view_audit_logs,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def accept_invitation(
    db: Session,
    *,
    user: User,
    invitation_id: uuid.UUID,
) -> ProjectMemberRead:
    invitation = db.get(ProjectInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    mark_expired_pending(db, invitation)
    if invitation.status == "expired":
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invitation has expired.")
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation is no longer pending.",
        )
    if normalize_invite_email(user.email) != invitation.email_normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signed-in user does not match this invitation.",
        )

    project = db.get(Project, invitation.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    existing = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    if existing is not None:
        invitation.status = "accepted"
        invitation.accepted_at = utcnow()
        db.commit()
        return ProjectMemberRead(
            user_id=user.id,
            email=user.email,
            role=existing.role,
            can_push_pull_secrets=existing.can_push_pull_secrets,
            can_manage_runtime_tokens=existing.can_manage_runtime_tokens,
            can_manage_team=existing.can_manage_team,
            can_view_audit_logs=existing.can_view_audit_logs,
            joined_at=existing.created_at,
        )

    role_final = invitation.role

    membership = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role_final,
        can_push_pull_secrets=invitation.can_push_pull_secrets,
        can_manage_runtime_tokens=invitation.can_manage_runtime_tokens,
        can_manage_team=invitation.can_manage_team,
        can_view_audit_logs=invitation.can_view_audit_logs,
        invited_by=invitation.invited_by_user_id,
    )
    db.add(membership)
    invitation.status = "accepted"
    invitation.accepted_at = utcnow()
    write_audit_log(
        db,
        project_id=project.id,
        user_id=user.id,
        action="invitation.accepted",
        metadata={
            "invitation_id": str(invitation.id),
            "email": invitation.email_normalized,
            "role": role_final,
            "can_push_pull_secrets": invitation.can_push_pull_secrets,
            "can_manage_runtime_tokens": invitation.can_manage_runtime_tokens,
            "can_manage_team": invitation.can_manage_team,
            "can_view_audit_logs": invitation.can_view_audit_logs,
        },
    )
    db.commit()
    db.refresh(membership)
    return ProjectMemberRead(
        user_id=user.id,
        email=user.email,
        role=membership.role,
        can_push_pull_secrets=membership.can_push_pull_secrets,
        can_manage_runtime_tokens=membership.can_manage_runtime_tokens,
        can_manage_team=membership.can_manage_team,
        can_view_audit_logs=membership.can_view_audit_logs,
        joined_at=membership.created_at,
    )


def reject_invitation(
    db: Session,
    *,
    user: User,
    invitation_id: uuid.UUID,
) -> None:
    invitation = db.get(ProjectInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    mark_expired_pending(db, invitation)
    if invitation.status != "pending":
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation is no longer pending.",
        )
    if normalize_invite_email(user.email) != invitation.email_normalized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signed-in user does not match this invitation.",
        )
    invitation.status = "rejected"
    invitation.rejected_at = utcnow()
    write_audit_log(
        db,
        project_id=invitation.project_id,
        user_id=user.id,
        action="invitation.rejected",
        metadata={"invitation_id": str(invitation.id), "email": invitation.email_normalized},
    )
    db.commit()
