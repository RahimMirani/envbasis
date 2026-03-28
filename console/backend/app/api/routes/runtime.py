from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.runtime_token import RuntimeToken
from app.schemas.runtime_fetch import RuntimeSecretsResponse
from app.services.audit import write_audit_log
from app.services.runtime_tokens import hash_runtime_token
from app.services.secrets import build_secret_payload, get_latest_secret_rows

router = APIRouter(prefix="/runtime")

runtime_bearer_scheme = HTTPBearer(auto_error=False)


def _get_runtime_token(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> RuntimeToken:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Runtime token is required.",
        )

    token_hash = hash_runtime_token(credentials.credentials)
    runtime_token = db.scalar(select(RuntimeToken).where(RuntimeToken.token_hash == token_hash))
    if runtime_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runtime token.",
        )

    now = datetime.now(timezone.utc)
    if runtime_token.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Runtime token has been revoked.",
        )

    if runtime_token.expires_at is not None and runtime_token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Runtime token has expired.",
        )

    return runtime_token


@router.post("/secrets", response_model=RuntimeSecretsResponse)
def fetch_runtime_secrets(
    credentials: HTTPAuthorizationCredentials | None = Depends(runtime_bearer_scheme),
    db: Session = Depends(get_db),
) -> RuntimeSecretsResponse:
    runtime_token = _get_runtime_token(credentials=credentials, db=db)

    latest_rows = get_latest_secret_rows(db, environment_id=runtime_token.environment_id)
    try:
        secrets, _ = build_secret_payload(latest_rows)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc

    runtime_token.last_used_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        project_id=runtime_token.project_id,
        environment_id=runtime_token.environment_id,
        user_id=None,
        action="runtime_token.used",
        metadata={"token_id": str(runtime_token.id), "name": runtime_token.name, "secret_count": len(secrets)},
    )
    db.commit()

    return RuntimeSecretsResponse(
        project_id=runtime_token.project_id,
        environment_id=runtime_token.environment_id,
        secrets=secrets,
        generated_at=datetime.now(timezone.utc),
    )
