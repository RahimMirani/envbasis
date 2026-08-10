from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ProjectAccess, enforce_project_permission, get_current_user, get_project_access, require_secret_management
from app.db.session import get_db
from app.models.environment import Environment
from app.models.project_secret_tag import ProjectSecretTag
from app.models.secret_folder import SecretFolder
from app.models.user import User
from app.schemas.secret_structure import (
    ProjectSecretTagCreate,
    ProjectSecretTagRead,
    ProjectSecretTagUpdate,
    SecretFolderCreate,
    SecretFolderListResponse,
    SecretFolderRead,
)
from app.services.audit import write_audit_log
from app.services.environments import get_project_environment_or_404
from app.services.secret_structure import (
    ensure_secret_folder,
    normalize_secret_path,
    normalize_secret_tags,
    path_is_within,
)
from app.services.secrets import get_latest_secret_rows

router = APIRouter(prefix="/projects")


def _folder_read(folder: SecretFolder) -> SecretFolderRead:
    return SecretFolderRead(
        id=folder.id,
        environment_id=folder.environment_id,
        path=folder.path,
        parent_path=folder.parent_path,
        name=folder.name,
        description=folder.description,
        created_by=folder.created_by,
        created_at=folder.created_at,
    )


def _tag_read(tag: ProjectSecretTag) -> ProjectSecretTagRead:
    return ProjectSecretTagRead(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        created_by=tag.created_by,
        created_at=tag.created_at,
    )


@router.get(
    "/{project_id}/environments/{environment_id}/folders",
    response_model=SecretFolderListResponse,
)
def list_secret_folders(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: Annotated[str, Query(max_length=512)] = "/",
    recursive: bool = False,
    project_access: ProjectAccess = Depends(get_project_access),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretFolderListResponse:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    try:
        selected_path = normalize_secret_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    enforce_project_permission(db, project_access=project_access, resource="folders", action="read", environment_id=environment.id, path=selected_path, legacy_allowed=True)

    rows = list(
        db.scalars(
            select(SecretFolder)
            .where(SecretFolder.environment_id == environment.id)
            .order_by(SecretFolder.path.asc())
        ).all()
    )
    if recursive:
        rows = [
            row
            for row in rows
            if path_is_within(row.path, selected_path, include_parent=False)
        ]
    else:
        rows = [row for row in rows if row.parent_path == selected_path]

    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_folders.listed",
        metadata={"path": selected_path, "recursive": recursive, "count": len(rows)},
    )
    db.commit()
    return SecretFolderListResponse(
        project_id=project_access.project.id,
        environment_id=environment.id,
        path=selected_path,
        recursive=recursive,
        folders=[_folder_read(row) for row in rows],
    )


@router.post(
    "/{project_id}/environments/{environment_id}/folders",
    response_model=SecretFolderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_secret_folder(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: SecretFolderCreate,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecretFolderRead:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    if payload.path == "/":
        raise HTTPException(status_code=409, detail="The root folder already exists.")
    enforce_project_permission(db, project_access=project_access, resource="folders", action="write", environment_id=environment.id, path=payload.path, legacy_allowed=project_access.can_push_pull_secrets)
    existing = db.scalar(
        select(SecretFolder).where(
            SecretFolder.environment_id == environment.id,
            SecretFolder.path == payload.path,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Folder already exists.")

    created = ensure_secret_folder(
        db,
        environment_id=environment.id,
        path=payload.path,
        description=payload.description,
        created_by=current_user.id,
    )
    folder = created[-1]
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_folder.created",
        metadata={"path": folder.path, "created_paths": [row.path for row in created]},
    )
    db.commit()
    db.refresh(folder)
    return _folder_read(folder)


@router.delete(
    "/{project_id}/environments/{environment_id}/folders",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_secret_folder(
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: Annotated[str, Query(max_length=512)],
    recursive: bool = False,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    environment = get_project_environment_or_404(
        db, project=project_access.project, environment_id=environment_id
    )
    try:
        selected_path = normalize_secret_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if selected_path == "/":
        raise HTTPException(status_code=422, detail="The root folder cannot be deleted.")
    enforce_project_permission(db, project_access=project_access, resource="folders", action="write", environment_id=environment.id, path=selected_path, legacy_allowed=project_access.can_push_pull_secrets)

    folder = db.scalar(
        select(SecretFolder).where(
            SecretFolder.environment_id == environment.id,
            SecretFolder.path == selected_path,
        )
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")

    descendants = list(
        db.scalars(
            select(SecretFolder).where(
                SecretFolder.environment_id == environment.id,
                SecretFolder.path.like(f"{selected_path}/%"),
            )
        ).all()
    )
    if descendants and not recursive:
        raise HTTPException(status_code=409, detail="Folder has child folders; use recursive=true.")

    active_secrets = [
        row
        for row in get_latest_secret_rows(db, environment_id=environment.id)
        if path_is_within(row.path, selected_path)
    ]
    if active_secrets:
        raise HTTPException(
            status_code=409,
            detail="Folder contains secrets. Move or delete the secrets before deleting the folder.",
        )

    deleted_paths = [row.path for row in descendants] + [folder.path]
    for row in sorted(descendants, key=lambda item: item.path.count("/"), reverse=True):
        db.delete(row)
    db.delete(folder)
    write_audit_log(
        db,
        project_id=project_access.project.id,
        environment_id=environment.id,
        user_id=current_user.id,
        action="secret_folder.deleted",
        metadata={"path": selected_path, "recursive": recursive, "deleted_paths": deleted_paths},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/secret-tags", response_model=list[ProjectSecretTagRead])
def list_project_secret_tags(
    project_id: uuid.UUID,
    project_access: ProjectAccess = Depends(get_project_access),
    db: Session = Depends(get_db),
) -> list[ProjectSecretTagRead]:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    enforce_project_permission(db, project_access=project_access, resource="tags", action="read", legacy_allowed=True)
    rows = db.scalars(
        select(ProjectSecretTag)
        .where(ProjectSecretTag.project_id == project_access.project.id)
        .order_by(ProjectSecretTag.name.asc())
    ).all()
    return [_tag_read(row) for row in rows]


@router.post(
    "/{project_id}/secret-tags",
    response_model=ProjectSecretTagRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_secret_tag(
    project_id: uuid.UUID,
    payload: ProjectSecretTagCreate,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectSecretTagRead:
    if project_id != project_access.project.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    enforce_project_permission(db, project_access=project_access, resource="tags", action="write", legacy_allowed=project_access.can_push_pull_secrets)
    name = normalize_secret_tags([payload.name])[0]
    existing = db.scalar(
        select(ProjectSecretTag).where(
            ProjectSecretTag.project_id == project_access.project.id,
            ProjectSecretTag.name == name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Tag already exists.")
    tag = ProjectSecretTag(
        project_id=project_access.project.id,
        name=name,
        color=payload.color,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(tag)
    db.flush()
    write_audit_log(
        db,
        project_id=project_access.project.id,
        user_id=current_user.id,
        action="secret_tag.created",
        metadata={"tag": name},
    )
    db.commit()
    db.refresh(tag)
    return _tag_read(tag)


@router.patch("/{project_id}/secret-tags/{tag_id}", response_model=ProjectSecretTagRead)
def update_project_secret_tag(
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    payload: ProjectSecretTagUpdate,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectSecretTagRead:
    tag = db.get(ProjectSecretTag, tag_id)
    if project_id != project_access.project.id or tag is None or tag.project_id != project_id:
        raise HTTPException(status_code=404, detail="Tag not found.")
    enforce_project_permission(db, project_access=project_access, resource="tags", action="write", legacy_allowed=project_access.can_push_pull_secrets)
    tag.color = payload.color
    tag.description = payload.description
    write_audit_log(
        db,
        project_id=project_id,
        user_id=current_user.id,
        action="secret_tag.updated",
        metadata={"tag": tag.name},
    )
    db.commit()
    db.refresh(tag)
    return _tag_read(tag)


@router.delete("/{project_id}/secret-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_secret_tag(
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    project_access: ProjectAccess = Depends(require_secret_management),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    tag = db.get(ProjectSecretTag, tag_id)
    if project_id != project_access.project.id or tag is None or tag.project_id != project_id:
        raise HTTPException(status_code=404, detail="Tag not found.")
    enforce_project_permission(db, project_access=project_access, resource="tags", action="write", legacy_allowed=project_access.can_push_pull_secrets)

    environments = db.scalars(
        select(Environment).where(Environment.project_id == project_access.project.id)
    ).all()
    in_use = any(
        tag.name in (secret.tags or [])
        for environment in environments
        for secret in get_latest_secret_rows(db, environment_id=environment.id)
    )
    if in_use:
        raise HTTPException(status_code=409, detail="Tag is assigned to one or more secrets.")
    db.delete(tag)
    write_audit_log(
        db,
        project_id=project_id,
        user_id=current_user.id,
        action="secret_tag.deleted",
        metadata={"tag": tag.name},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
