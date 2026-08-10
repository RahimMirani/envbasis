from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, enforce_project_permission, get_project_access, get_current_user, require_secret_management
from app.db.session import get_db
from app.models.secret_import import SecretImport
from app.models.user import User
from app.schemas.secret_import import SecretImportCreate, SecretImportRead, SecretImportUpdate
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.secret_structure import ensure_secret_folder

router = APIRouter(prefix="/projects")


def _read(rule: SecretImport) -> SecretImportRead:
    return SecretImportRead(
        id=rule.id,
        project_id=rule.project_id,
        target_environment_id=rule.target_environment_id,
        target_path=rule.target_path,
        source_environment_id=rule.source_environment_id,
        source_path=rule.source_path,
        recursive=rule.recursive,
        priority=rule.priority,
        enabled=rule.enabled,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/{project_id}/secret-imports", response_model=list[SecretImportRead])
def list_secret_imports(
    project_id: uuid.UUID,
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> list[SecretImportRead]:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    enforce_project_permission(db, project_access=project_access, resource="imports", action="read", legacy_allowed=True)
    rows = db.scalars(
        select(SecretImport)
        .where(SecretImport.project_id == project_id)
        .order_by(
            SecretImport.target_environment_id.asc(),
            SecretImport.target_path.asc(),
            SecretImport.priority.desc(),
        )
    ).all()
    return [_read(row) for row in rows]


@router.post(
    "/{project_id}/secret-imports",
    response_model=SecretImportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_secret_import(
    project_id: uuid.UUID,
    payload: SecretImportCreate,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretImportRead:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    get_project_environment_or_404(
        db, project=project_access.project, environment_id=payload.target_environment_id
    )
    enforce_project_permission(db, project_access=project_access, resource="imports", action="write", environment_id=payload.target_environment_id, path=payload.target_path, legacy_allowed=project_access.can_push_pull_secrets)
    get_project_environment_or_404(
        db, project=project_access.project, environment_id=payload.source_environment_id
    )
    if (
        payload.target_environment_id == payload.source_environment_id
        and payload.target_path == payload.source_path
    ):
        raise HTTPException(status_code=422, detail="An import cannot target its own source.")
    existing = db.scalar(
        select(SecretImport).where(
            SecretImport.target_environment_id == payload.target_environment_id,
            SecretImport.target_path == payload.target_path,
            SecretImport.source_environment_id == payload.source_environment_id,
            SecretImport.source_path == payload.source_path,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This import already exists.")

    ensure_secret_folder(
        db,
        environment_id=payload.target_environment_id,
        path=payload.target_path,
        created_by=current_user.id,
    )
    rule = SecretImport(
        project_id=project_id,
        target_environment_id=payload.target_environment_id,
        target_path=payload.target_path,
        source_environment_id=payload.source_environment_id,
        source_path=payload.source_path,
        recursive=payload.recursive,
        priority=payload.priority,
        enabled=payload.enabled,
        created_by=current_user.id,
    )
    db.add(rule)
    db.flush()
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=payload.target_environment_id,
        user_id=current_user.id,
        action="secret_import.created",
        metadata={
            "import_id": str(rule.id),
            "target_path": rule.target_path,
            "source_environment_id": str(rule.source_environment_id),
            "source_path": rule.source_path,
            "priority": rule.priority,
        },
    )
    db.commit()
    db.refresh(rule)
    return _read(rule)


@router.patch("/{project_id}/secret-imports/{import_id}", response_model=SecretImportRead)
def update_secret_import(
    project_id: uuid.UUID,
    import_id: uuid.UUID,
    payload: SecretImportUpdate,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretImportRead:
    rule = db.get(SecretImport, import_id)
    if project_id != project_access.project.id or rule is None or rule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Secret import not found.")
    enforce_project_permission(db, project_access=project_access, resource="imports", action="write", environment_id=rule.target_environment_id, path=rule.target_path, legacy_allowed=project_access.can_push_pull_secrets)
    for field in payload.model_fields_set:
        setattr(rule, field, getattr(payload, field))
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=rule.target_environment_id,
        user_id=current_user.id,
        action="secret_import.updated",
        metadata={"import_id": str(rule.id), "changes": sorted(payload.model_fields_set)},
    )
    db.commit()
    db.refresh(rule)
    return _read(rule)


@router.delete("/{project_id}/secret-imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_import(
    project_id: uuid.UUID,
    import_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    rule = db.get(SecretImport, import_id)
    if project_id != project_access.project.id or rule is None or rule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Secret import not found.")
    enforce_project_permission(db, project_access=project_access, resource="imports", action="write", environment_id=rule.target_environment_id, path=rule.target_path, legacy_allowed=project_access.can_push_pull_secrets)
    target_environment_id = rule.target_environment_id
    db.delete(rule)
    write_audit_log(
        db,
        project_id=project_id,
        environment_id=target_environment_id,
        user_id=current_user.id,
        action="secret_import.deleted",
        metadata={"import_id": str(import_id)},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
