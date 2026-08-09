from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.access_control import router as access_control_router
from app.api.routes.audit_logs import router as audit_logs_router
from app.api.routes.audit_logs import unified_router as unified_audit_logs_router
from app.api.routes.cli_auth import router as cli_auth_router
from app.api.routes.health import router as health_router
from app.api.routes.invitations import router as invitations_router
from app.api.routes.machine_identities import router as machine_identities_router
from app.api.routes.projects import router as projects_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.runtime_tokens import router as runtime_tokens_router
from app.api.routes.secrets import router as secrets_router
from app.api.routes.secret_structure import router as secret_structure_router
from app.api.routes.secret_imports import router as secret_imports_router
from app.api.routes.secret_history import router as secret_history_router
from app.api.routes.webhooks import router as webhooks_router
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(access_control_router, tags=["access-control"])
api_router.include_router(approvals_router, tags=["approvals"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(invitations_router, tags=["invitations"])
api_router.include_router(machine_identities_router, tags=["machine-identities"])
api_router.include_router(audit_logs_router, tags=["audit-logs"])
api_router.include_router(unified_audit_logs_router, tags=["audit-logs"])
api_router.include_router(cli_auth_router, tags=["cli-auth"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(projects_router, tags=["projects"])
api_router.include_router(runtime_router, tags=["runtime"])
api_router.include_router(secrets_router, tags=["secrets"])
api_router.include_router(secret_structure_router, tags=["secret-structure"])
api_router.include_router(secret_imports_router, tags=["secret-imports"])
api_router.include_router(secret_history_router, tags=["secret-history"])
api_router.include_router(runtime_tokens_router, tags=["runtime-tokens"])
if settings.webhooks_enabled:
    api_router.include_router(webhooks_router, tags=["webhooks"])
