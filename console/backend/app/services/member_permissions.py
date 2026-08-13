from __future__ import annotations

from typing import Any


MEMBER_PERMISSION_FIELDS = (
    "can_push_pull_secrets",
    "can_manage_runtime_tokens",
    "can_manage_team",
    "can_view_audit_logs",
)


def get_undelegable_permissions(
    *,
    actor_permissions: Any,
    requested_permissions: Any,
) -> list[str]:
    return [
        permission
        for permission in MEMBER_PERMISSION_FIELDS
        if getattr(requested_permissions, permission, None) is True
        and not getattr(actor_permissions, permission)
    ]
