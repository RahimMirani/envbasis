from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.approval import ApprovalPolicy
from app.services.secret_structure import normalize_secret_path, path_is_within


def get_matching_approval_policy(
    db: Session,
    *,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    path: str,
    operation: str,
) -> ApprovalPolicy | None:
    selected_path = normalize_secret_path(path)
    policies = db.scalars(
        select(ApprovalPolicy).where(
            ApprovalPolicy.project_id == project_id,
            ApprovalPolicy.enabled.is_(True),
        )
    ).all()
    matches = [
        policy
        for policy in policies
        if operation in policy.actions
        and policy.environment_id in {None, environment_id}
        and (
            path_is_within(selected_path, policy.path)
            if policy.recursive
            else selected_path == policy.path
        )
    ]
    return next(
        iter(
            sorted(
                matches,
                key=lambda policy: (
                    policy.environment_id is not None,
                    len(policy.path),
                    str(policy.id),
                ),
                reverse=True,
            )
        ),
        None,
    )
