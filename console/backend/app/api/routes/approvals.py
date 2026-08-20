from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, enforce_project_permission, get_current_user, get_project_access, require_project_owner, require_secret_management
from app.api.routes.secrets import _create_secret_version, _get_latest_secret_map, _validate_secret_key
from app.db.session import get_db
from app.models.access_role import AccessRole, AccessRoleAssignment
from app.models.approval import ApprovalPolicy, ApprovalRequest, ApprovalRequestEvent
from app.models.user import User
from app.models.project import Project
from app.models.environment import Environment
from app.schemas.approval import (
    ApprovalAction,
    ApprovalEventRead,
    ApprovalPolicyCreate,
    ApprovalPolicyRead,
    ApprovalPolicyUpdate,
    ApprovalRequestRead,
    ApprovalStep,
    SecretChangeProposal,
)
from app.services.approvals import get_matching_approval_policy
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.project_encryption import decrypt_project_secret, encrypt_project_secret
from app.services.secret_structure import normalize_secret_path, normalize_secret_tags
from app.services.secrets import permanently_delete_secret

router = APIRouter(prefix="/projects")


def _policy_read(policy: ApprovalPolicy) -> ApprovalPolicyRead:
    return ApprovalPolicyRead(
        id=policy.id,
        project_id=policy.project_id,
        name=policy.name,
        environment_id=policy.environment_id,
        path=policy.path,
        recursive=policy.recursive,
        actions=list(policy.actions),
        steps=[ApprovalStep(**step) for step in policy.steps],
        prevent_self_approval=policy.prevent_self_approval,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _events(db: Session, request_id: uuid.UUID) -> list[ApprovalRequestEvent]:
    return list(db.scalars(select(ApprovalRequestEvent).where(ApprovalRequestEvent.request_id == request_id).order_by(ApprovalRequestEvent.created_at, ApprovalRequestEvent.id)).all())


def _request_read(db: Session, request: ApprovalRequest) -> ApprovalRequestRead:
    policy = db.get(ApprovalPolicy, request.policy_id)
    return ApprovalRequestRead(
        id=request.id,
        policy_id=request.policy_id,
        project_id=request.project_id,
        environment_id=request.environment_id,
        path=request.path,
        secret_key=request.secret_key,
        operation=request.operation,
        metadata=dict(request.secret_metadata or {}),
        status=request.status,
        current_step=request.current_step,
        total_steps=len(policy.steps) if policy else 0,
        author_id=request.author_id,
        created_at=request.created_at,
        resolved_at=request.resolved_at,
        events=[ApprovalEventRead.model_validate(event, from_attributes=True) for event in _events(db, request.id)],
    )


def _validate_policy(db: Session, *, project_id: uuid.UUID, payload) -> str:
    path = normalize_secret_path(payload.path or "/")
    if payload.environment_id is not None:
        environment = db.get(Environment, payload.environment_id)
        if environment is None or environment.project_id != project_id:
            raise HTTPException(status_code=422, detail="Policy environment is not in this project.")
    project = db.get(Project, project_id)
    for step in payload.steps or []:
        for role_id in step.approver_role_ids:
            role = db.get(AccessRole, role_id)
            if role is None or (
                role.project_id != project_id
                and (project is None or role.organization_id != project.organization_id)
            ):
                raise HTTPException(status_code=422, detail="Approver role is not available to this project.")
    return path


@router.get("/{project_id}/approval-policies", response_model=list[ApprovalPolicyRead])
def list_approval_policies(project_access: ProjectAccess = Depends(require_project_owner), db: Session = Depends(get_db)) -> list[ApprovalPolicyRead]:
    rows = db.scalars(select(ApprovalPolicy).where(ApprovalPolicy.project_id == project_access.project.id).order_by(ApprovalPolicy.name)).all()
    return [_policy_read(row) for row in rows]


@router.post("/{project_id}/approval-policies", response_model=ApprovalPolicyRead, status_code=201)
def create_approval_policy(payload: ApprovalPolicyCreate, project_access: ProjectAccess = Depends(require_project_owner), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApprovalPolicyRead:
    normalized_path = _validate_policy(db, project_id=project_access.project.id, payload=payload)
    policy = ApprovalPolicy(
        project_id=project_access.project.id,
        name=payload.name.strip(),
        environment_id=payload.environment_id,
        path=normalized_path,
        recursive=payload.recursive,
        actions=list(dict.fromkeys(payload.actions)),
        steps=[step.model_dump(mode="json") for step in payload.steps],
        prevent_self_approval=payload.prevent_self_approval,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(policy)
    db.flush()
    write_audit_log(db, project_id=policy.project_id, user_id=current_user.id, action="approval_policy.created", metadata={"policy_id": str(policy.id), "path": policy.path})
    db.commit()
    db.refresh(policy)
    return _policy_read(policy)


@router.patch("/{project_id}/approval-policies/{policy_id}", response_model=ApprovalPolicyRead)
def update_approval_policy(policy_id: uuid.UUID, payload: ApprovalPolicyUpdate, project_access: ProjectAccess = Depends(require_project_owner), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApprovalPolicyRead:
    policy = db.get(ApprovalPolicy, policy_id)
    if policy is None or policy.project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Approval policy not found.")
    _validate_policy(db, project_id=policy.project_id, payload=payload)
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if field == "path" and value is not None:
            value = normalize_secret_path(value)
        elif field == "steps" and value is not None:
            value = [step.model_dump(mode="json") for step in value]
        setattr(policy, field, value)
    write_audit_log(db, project_id=policy.project_id, user_id=current_user.id, action="approval_policy.updated", metadata={"policy_id": str(policy.id)})
    db.commit()
    db.refresh(policy)
    return _policy_read(policy)


@router.delete("/{project_id}/approval-policies/{policy_id}", status_code=204)
def delete_approval_policy(policy_id: uuid.UUID, project_access: ProjectAccess = Depends(require_project_owner), db: Session = Depends(get_db)) -> Response:
    policy = db.get(ApprovalPolicy, policy_id)
    if policy is None or policy.project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Approval policy not found.")
    pending = db.scalar(select(ApprovalRequest.id).where(ApprovalRequest.policy_id == policy.id, ApprovalRequest.status == "pending").limit(1))
    if pending is not None:
        raise HTTPException(status_code=409, detail="Disable the policy or resolve its pending requests before deleting it.")
    db.delete(policy)
    db.commit()
    return Response(status_code=204)


@router.post("/{project_id}/approval-requests", response_model=ApprovalRequestRead, status_code=201)
def create_approval_request(payload: SecretChangeProposal, project_access: ProjectAccess = Depends(require_secret_management), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApprovalRequestRead:
    environment = get_project_environment_or_404(db, project=project_access.project, environment_id=payload.environment_id)
    path = normalize_secret_path(payload.path)
    enforce_project_permission(db, project_access=project_access, resource="secrets", action="write", environment_id=environment.id, path=path, legacy_allowed=project_access.can_push_pull_secrets)
    key = _validate_secret_key(payload.secret_key)
    policy = get_matching_approval_policy(db, project_id=project_access.project.id, environment_id=environment.id, path=path, operation=payload.operation)
    if policy is None:
        raise HTTPException(status_code=422, detail="No enabled approval policy matches this change.")
    latest = _get_latest_secret_map(db, environment_id=environment.id).get((path, key))
    if payload.operation == "create" and latest is not None and not latest.is_deleted:
        raise HTTPException(status_code=409, detail="Secret already exists.")
    if payload.operation in {"update", "delete"} and (latest is None or latest.is_deleted):
        raise HTTPException(status_code=404, detail="Secret not found.")
    encrypted_value = None
    key_version = None
    if payload.value is not None:
        encrypted_value, key_version = encrypt_project_secret(db, project_id=project_access.project.id, value=payload.value)
    request = ApprovalRequest(
        policy_id=policy.id,
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=path,
        secret_key=key,
        operation=payload.operation,
        encrypted_value=encrypted_value,
        encryption_key_version=key_version,
        secret_metadata=dict(payload.metadata),
        author_id=current_user.id,
    )
    db.add(request)
    db.flush()
    db.add(ApprovalRequestEvent(request_id=request.id, actor_id=current_user.id, action="created", step=0, comment=payload.comment, created_at=datetime.now(timezone.utc)))
    write_audit_log(db, project_id=request.project_id, environment_id=request.environment_id, user_id=current_user.id, action="approval_request.created", metadata={"request_id": str(request.id), "operation": request.operation, "key": key, "path": path})
    db.commit()
    db.refresh(request)
    return _request_read(db, request)


@router.get("/{project_id}/approval-requests", response_model=list[ApprovalRequestRead])
def list_approval_requests(project_access: ProjectAccess = Depends(get_project_access), db: Session = Depends(get_db)) -> list[ApprovalRequestRead]:
    rows = db.scalars(select(ApprovalRequest).where(ApprovalRequest.project_id == project_access.project.id).order_by(ApprovalRequest.created_at.desc())).all()
    return [_request_read(db, row) for row in rows]


def _is_approver(db: Session, *, user_id: uuid.UUID, step: ApprovalStep) -> bool:
    if user_id in step.approver_user_ids:
        return True
    if not step.approver_role_ids:
        return False
    return db.scalar(select(AccessRoleAssignment.id).where(AccessRoleAssignment.user_id == user_id, AccessRoleAssignment.role_id.in_(step.approver_role_ids)).limit(1)) is not None


def _apply_request(db: Session, request: ApprovalRequest, actor: User) -> None:
    latest = _get_latest_secret_map(db, environment_id=request.environment_id).get((request.path, request.secret_key))
    metadata = dict(request.secret_metadata or {})
    if request.operation == "delete":
        deleted = permanently_delete_secret(
            db,
            environment_id=request.environment_id,
            path=request.path,
            key=request.secret_key,
        )
        if deleted is not None:
            write_audit_log(
                db,
                project_id=request.project_id,
                environment_id=request.environment_id,
                user_id=actor.id,
                action="secret.deleted",
                metadata={**deleted.audit_metadata(), "via": "approval"},
            )
        return

    next_version = 1 if latest is None else latest.version + 1
    value = decrypt_project_secret(db, project_id=request.project_id, encrypted_value=request.encrypted_value, encryption_key_version=request.encryption_key_version)
    _create_secret_version(
        db=db,
        project_id=request.project_id,
        environment_id=request.environment_id,
        key=request.secret_key,
        value=value,
        version=next_version,
        updated_by=actor.id,
        path=request.path,
        tags=normalize_secret_tags(metadata.get("tags", list(latest.tags or []) if latest else [])),
        description=metadata.get("description", latest.description if latest else None),
        owner=metadata.get("owner", latest.owner if latest else None),
        service=metadata.get("service", latest.service if latest else None),
        rotation_interval_days=metadata.get("rotation_interval_days", latest.rotation_interval_days if latest else None),
        custom_metadata=metadata.get("custom_metadata", dict(latest.custom_metadata or {}) if latest else {}),
        is_reference=metadata.get("is_reference", latest.is_reference if latest else None),
    )


@router.post("/{project_id}/approval-requests/{request_id}/actions", response_model=ApprovalRequestRead)
def act_on_approval_request(request_id: uuid.UUID, payload: ApprovalAction, project_access: ProjectAccess = Depends(get_project_access), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApprovalRequestRead:
    request = db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update())
    if request is None or request.project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    policy = db.get(ApprovalPolicy, request.policy_id)
    if payload.action == "comment":
        db.add(ApprovalRequestEvent(request_id=request.id, actor_id=current_user.id, action="comment", step=request.current_step, comment=payload.comment, created_at=datetime.now(timezone.utc)))
    elif payload.action == "cancel":
        if current_user.id != request.author_id and project_access.role != "owner":
            raise HTTPException(status_code=403, detail="Only the author or project owner can cancel this request.")
        if request.status != "pending":
            raise HTTPException(status_code=409, detail="Only pending requests can be cancelled.")
        request.status = "cancelled"
        request.resolved_at = datetime.now(timezone.utc)
        db.add(ApprovalRequestEvent(request_id=request.id, actor_id=current_user.id, action="cancelled", step=request.current_step, comment=payload.comment, created_at=datetime.now(timezone.utc)))
    elif payload.action in {"approve", "reject"}:
        if request.status != "pending":
            raise HTTPException(status_code=409, detail="This request is no longer pending.")
        step = ApprovalStep(**policy.steps[request.current_step])
        if not _is_approver(db, user_id=current_user.id, step=step):
            raise HTTPException(status_code=403, detail="You are not an approver for the current step.")
        if policy.prevent_self_approval and current_user.id == request.author_id:
            raise HTTPException(status_code=403, detail="Request authors cannot approve their own changes.")
        existing = db.scalar(select(ApprovalRequestEvent.id).where(ApprovalRequestEvent.request_id == request.id, ApprovalRequestEvent.actor_id == current_user.id, ApprovalRequestEvent.action == "approved", ApprovalRequestEvent.step == request.current_step).limit(1))
        if existing is not None:
            raise HTTPException(status_code=409, detail="You already approved this step.")
        event_action = "approved" if payload.action == "approve" else "rejected"
        db.add(ApprovalRequestEvent(request_id=request.id, actor_id=current_user.id, action=event_action, step=request.current_step, comment=payload.comment, created_at=datetime.now(timezone.utc)))
        if payload.action == "reject":
            request.status = "rejected"
            request.resolved_at = datetime.now(timezone.utc)
        else:
            db.flush()
            approvals = len(db.scalars(select(ApprovalRequestEvent.id).where(ApprovalRequestEvent.request_id == request.id, ApprovalRequestEvent.action == "approved", ApprovalRequestEvent.step == request.current_step)).all())
            if approvals >= step.min_approvals:
                request.current_step += 1
                if request.current_step >= len(policy.steps):
                    _apply_request(db, request, current_user)
                    request.status = "approved"
                    request.resolved_at = datetime.now(timezone.utc)
    write_audit_log(db, project_id=request.project_id, environment_id=request.environment_id, user_id=current_user.id, action=f"approval_request.{payload.action}", metadata={"request_id": str(request.id), "status": request.status, "step": request.current_step, "comment": payload.comment})
    db.commit()
    db.refresh(request)
    return _request_read(db, request)
