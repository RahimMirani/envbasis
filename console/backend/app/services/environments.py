from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.environment import Environment
from app.models.project import Project


def get_project_environment_or_404(
    db: Session,
    *,
    project: Project,
    environment_id: uuid.UUID,
) -> Environment:
    environment = db.get(Environment, environment_id)
    if environment is None or environment.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Environment not found for this project.",
        )

    return environment

