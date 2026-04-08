from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.audit_logs import router as audit_logs_router
from app.api.routes.audit_logs import unified_router as unified_audit_logs_router
from app.api.routes.cli_auth import router as cli_auth_router
from app.api.routes.health import router as health_router
from app.api.routes.invitations import router as invitations_router
from app.api.routes.projects import router as projects_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.runtime_tokens import router as runtime_tokens_router
from app.api.routes.secrets import router as secrets_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(invitations_router, tags=["invitations"])
api_router.include_router(audit_logs_router, tags=["audit-logs"])
api_router.include_router(unified_audit_logs_router, tags=["audit-logs"])
api_router.include_router(cli_auth_router, tags=["cli-auth"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(projects_router, tags=["projects"])
api_router.include_router(runtime_router, tags=["runtime"])
api_router.include_router(secrets_router, tags=["secrets"])
api_router.include_router(runtime_tokens_router, tags=["runtime-tokens"])
