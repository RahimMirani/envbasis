from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.cli_auth_session import (
    CLI_AUTH_STATUS_APPROVED,
    CLI_AUTH_STATUS_CONSUMED,
    CLI_AUTH_STATUS_DENIED,
    CLI_AUTH_STATUS_EXPIRED,
    CLI_AUTH_STATUS_PENDING,
    CliAuthSession,
)
from app.models.user import User
from app.schemas.cli_auth import (
    CliAuthCodeRequest,
    CliAuthLogoutRequest,
    CliAuthLogoutResponse,
    CliAuthRefreshRequest,
    CliAuthResolveResponse,
    CliAuthStartRequest,
    CliAuthStartResponse,
    CliAuthTokenRequest,
    CliAuthTokenSuccessResponse,
    CliAuthUserRead,
)
from app.services.audit import write_cli_auth_audit_log
from app.services.cli_auth import (
    build_verification_urls,
    expire_session_if_needed,
    generate_device_code,
    generate_user_code,
    hash_cli_auth_token,
    issue_cli_token_pair,
    normalize_user_code,
    revoke_refresh_token_family,
    rotate_cli_refresh_token,
    utcnow,
)

router = APIRouter(prefix="/cli/auth")


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _build_resolve_response(session: CliAuthSession) -> CliAuthResolveResponse:
    return CliAuthResolveResponse(
        status=session.status,
        user_code=session.user_code,
        client_name=session.client_name,
        device_name=session.device_name,
        cli_version=session.cli_version,
        platform=session.platform,
        expires_at=session.expires_at,
        requested_at=session.created_at,
    )


def _build_cli_auth_audit_metadata(session: CliAuthSession) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if session.client_name:
        metadata["client_name"] = session.client_name
    if session.device_name:
        metadata["device_name"] = session.device_name
    if session.cli_version:
        metadata["cli_version"] = session.cli_version
    if session.platform:
        metadata["platform"] = session.platform
    return metadata


def _get_session_by_user_code_or_404(db: Session, *, user_code: str) -> CliAuthSession:
    normalized_code = normalize_user_code(user_code)
    session = db.scalar(
        select(CliAuthSession).where(CliAuthSession.user_code_normalized == normalized_code)
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid user code.",
        )

    return session


def _expire_session_and_audit(db: Session, *, session: CliAuthSession) -> bool:
    expired = expire_session_if_needed(session)
    if expired:
        write_cli_auth_audit_log(
            db,
            action="cli_auth.expired",
            cli_auth_session_id=session.id,
            user_id=session.approved_by_user_id,
            metadata=_build_cli_auth_audit_metadata(session),
        )
    return expired


@router.post("/start", response_model=CliAuthStartResponse)
def start_cli_auth(
    payload: CliAuthStartRequest,
    db: Session = Depends(get_db),
) -> CliAuthStartResponse:
    ttl_seconds = settings.cli_auth_device_code_ttl_seconds
    for _ in range(6):
        device_code = generate_device_code()
        user_code = generate_user_code()
        session = CliAuthSession(
            device_code_hash=hash_cli_auth_token(device_code),
            user_code=user_code,
            user_code_normalized=normalize_user_code(user_code),
            status=CLI_AUTH_STATUS_PENDING,
            client_name=_clean_optional_text(payload.client_name),
            device_name=_clean_optional_text(payload.device_name),
            cli_version=_clean_optional_text(payload.cli_version),
            platform=_clean_optional_text(payload.platform),
            expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        )
        db.add(session)
        try:
            db.flush()
            write_cli_auth_audit_log(
                db,
                action="cli_auth.started",
                cli_auth_session_id=session.id,
                metadata={
                    "client_name": session.client_name,
                    "device_name": session.device_name,
                    "cli_version": session.cli_version,
                    "platform": session.platform,
                },
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            continue

        verification_url, verification_url_complete = build_verification_urls(user_code)
        return CliAuthStartResponse(
            device_code=device_code,
            user_code=user_code,
            verification_url=verification_url,
            verification_url_complete=verification_url_complete,
            expires_in=ttl_seconds,
            interval=settings.cli_auth_poll_interval_seconds,
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not create CLI auth session. Please try again.",
    )


@router.post("/resolve", response_model=CliAuthResolveResponse)
def resolve_cli_auth(
    payload: CliAuthCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CliAuthResolveResponse:
    _ = current_user
    session = _get_session_by_user_code_or_404(db, user_code=payload.user_code)
    if _expire_session_and_audit(db, session=session):
        db.commit()

    return _build_resolve_response(session)


@router.post("/verify", response_model=CliAuthResolveResponse)
def verify_cli_auth(
    payload: CliAuthCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CliAuthResolveResponse:
    session = _get_session_by_user_code_or_404(db, user_code=payload.user_code)
    state_changed = _expire_session_and_audit(db, session=session)
    if session.status != CLI_AUTH_STATUS_PENDING:
        if state_changed:
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"CLI auth request is no longer pending (status: {session.status}).",
        )

    now = utcnow()
    session.status = CLI_AUTH_STATUS_APPROVED
    session.approved_by_user_id = current_user.id
    session.approved_at = now
    write_cli_auth_audit_log(
        db,
        action="cli_auth.approved",
        cli_auth_session_id=session.id,
        user_id=current_user.id,
        metadata=_build_cli_auth_audit_metadata(session),
    )
    db.commit()
    return _build_resolve_response(session)


@router.post("/deny", response_model=CliAuthResolveResponse)
def deny_cli_auth(
    payload: CliAuthCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CliAuthResolveResponse:
    session = _get_session_by_user_code_or_404(db, user_code=payload.user_code)
    state_changed = _expire_session_and_audit(db, session=session)
    if session.status != CLI_AUTH_STATUS_PENDING:
        if state_changed:
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"CLI auth request is no longer pending (status: {session.status}).",
        )

    session.status = CLI_AUTH_STATUS_DENIED
    session.denied_at = utcnow()
    write_cli_auth_audit_log(
        db,
        action="cli_auth.denied",
        cli_auth_session_id=session.id,
        user_id=current_user.id,
        metadata=_build_cli_auth_audit_metadata(session),
    )
    db.commit()
    return _build_resolve_response(session)


@router.post("/token", response_model=CliAuthTokenSuccessResponse)
def exchange_cli_auth_token(
    payload: CliAuthTokenRequest,
    db: Session = Depends(get_db),
) -> CliAuthTokenSuccessResponse | JSONResponse:
    session = db.scalar(
        select(CliAuthSession).where(
            CliAuthSession.device_code_hash == hash_cli_auth_token(payload.device_code)
        )
    )
    if session is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "invalid_device_code"},
        )

    now = utcnow()
    if _expire_session_and_audit(db, session=session):
        db.commit()

    if session.status == CLI_AUTH_STATUS_PENDING:
        if (
            session.last_polled_at is not None
            and (now - session.last_polled_at).total_seconds() < settings.cli_auth_poll_interval_seconds
        ):
            session.last_polled_at = now
            db.commit()
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "slow_down",
                    "interval": settings.cli_auth_poll_interval_seconds,
                },
            )

        session.last_polled_at = now
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "error": "authorization_pending",
                "interval": settings.cli_auth_poll_interval_seconds,
            },
        )

    if session.status == CLI_AUTH_STATUS_DENIED:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "access_denied"},
        )
    if session.status == CLI_AUTH_STATUS_EXPIRED:
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={"error": "expired_token"},
        )
    if session.status == CLI_AUTH_STATUS_CONSUMED:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "already_used"},
        )
    if session.status != CLI_AUTH_STATUS_APPROVED:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "already_used"},
        )

    if session.approved_by_user_id is None:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "access_denied"},
        )

    user = db.get(User, session.approved_by_user_id)
    if user is None:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "access_denied"},
        )

    token_pair = issue_cli_token_pair(db, user=user, cli_auth_session=session)
    session.status = CLI_AUTH_STATUS_CONSUMED
    session.consumed_at = now
    session.last_polled_at = now
    write_cli_auth_audit_log(
        db,
        action="cli_auth.token_issued",
        cli_auth_session_id=session.id,
        user_id=user.id,
        metadata={"refresh_token_id": str(token_pair.refresh_token_id)},
    )
    write_cli_auth_audit_log(
        db,
        action="cli_auth.token_consumed",
        cli_auth_session_id=session.id,
        user_id=user.id,
        metadata=_build_cli_auth_audit_metadata(session),
    )
    db.commit()
    return CliAuthTokenSuccessResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type="bearer",
        expires_in=token_pair.expires_in,
        expires_at=token_pair.expires_at,
        user=CliAuthUserRead(id=user.id, email=user.email),
    )


@router.post("/refresh", response_model=CliAuthTokenSuccessResponse)
def refresh_cli_auth_token(
    payload: CliAuthRefreshRequest,
    db: Session = Depends(get_db),
) -> CliAuthTokenSuccessResponse | JSONResponse:
    try:
        token_pair, user, previous_refresh_token = rotate_cli_refresh_token(
            db,
            refresh_token=payload.refresh_token,
        )
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "invalid_refresh_token"},
        )

    write_cli_auth_audit_log(
        db,
        action="cli_auth.refresh_succeeded",
        cli_auth_session_id=previous_refresh_token.cli_auth_session_id,
        user_id=user.id,
        metadata={
            "previous_refresh_token_id": str(previous_refresh_token.id),
            "refresh_token_id": str(token_pair.refresh_token_id),
        },
    )
    db.commit()
    return CliAuthTokenSuccessResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type="bearer",
        expires_in=token_pair.expires_in,
        expires_at=token_pair.expires_at,
        user=CliAuthUserRead(id=user.id, email=user.email),
    )


@router.post("/logout", response_model=CliAuthLogoutResponse)
def logout_cli_auth(
    payload: CliAuthLogoutRequest,
    db: Session = Depends(get_db),
) -> CliAuthLogoutResponse:
    refresh_token_row = revoke_refresh_token_family(
        db,
        refresh_token=payload.refresh_token,
    )
    if refresh_token_row is not None:
        write_cli_auth_audit_log(
            db,
            action="cli_auth.logged_out",
            cli_auth_session_id=refresh_token_row.cli_auth_session_id,
            user_id=refresh_token_row.user_id,
            metadata={"refresh_token_id": str(refresh_token_row.id)},
        )
    db.commit()
    return CliAuthLogoutResponse(revoked=True)
