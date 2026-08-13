from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import logging
import re
from typing import Awaitable, Callable

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.api_idempotency_record import ApiIdempotencyRecord


logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,255}")
SENSITIVE_CREATE_PATTERNS = (
    re.compile(r"^/api/v1/projects$"),
    re.compile(r"^/api/v1/projects/[^/]+/environments$"),
    re.compile(r"^/api/v1/projects/[^/]+/environments/[^/]+/secrets$"),
    re.compile(r"^/api/v1/projects/[^/]+/environments/[^/]+/secrets/push$"),
    re.compile(r"^/api/v1/projects/[^/]+/environments/[^/]+/runtime-tokens$"),
    re.compile(r"^/api/v1/projects/[^/]+/machine-identities$"),
    re.compile(r"^/api/v1/projects/[^/]+/webhooks$"),
    re.compile(r"^/api/v1/projects/[^/]+/invitations$"),
    re.compile(r"^/api/v1/projects/[^/]+/runtime-tokens/[^/]+/share$"),
)
REPLAYED_RESPONSE_HEADERS = {
    "cache-control",
    "content-type",
    "expires",
    "location",
    "pragma",
}


@dataclass(frozen=True)
class IdempotencyClaim:
    record: ApiIdempotencyRecord | None = None
    replay: Response | None = None
    error: Response | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_sensitive_create_request(request: Request) -> bool:
    return request.method == "POST" and any(
        pattern.fullmatch(request.url.path) for pattern in SENSITIVE_CREATE_PATTERNS
    )


def _fernet() -> Fernet:
    if not settings.api_idempotency_encryption_key:
        raise RuntimeError("API idempotency encryption is not configured.")
    try:
        return Fernet(settings.api_idempotency_encryption_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("API idempotency encryption key is invalid.") from exc


def _subject_hash(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        subject = f"authorization:{authorization}"
    else:
        client_ip = request.client.host if request.client else "unknown"
        subject = f"ip:{client_ip}"
    return sha256(subject.encode("utf-8")).hexdigest()


def _request_hash(request: Request, body: bytes) -> str:
    canonical = b"\n".join(
        [
            request.method.encode("ascii"),
            request.url.path.encode("utf-8"),
            request.url.query.encode("utf-8"),
            body,
        ]
    )
    return sha256(canonical).hexdigest()


def _error_response(request: Request, *, status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def _replay_response(record: ApiIdempotencyRecord) -> Response:
    if record.encrypted_response_body is None or record.response_status is None:
        raise RuntimeError("Stored idempotency response is incomplete.")
    try:
        body = _fernet().decrypt(record.encrypted_response_body)
    except InvalidToken as exc:
        raise RuntimeError("Stored idempotency response cannot be decrypted.") from exc
    headers = dict(record.response_headers or {})
    headers["Idempotency-Replayed"] = "true"
    headers["Cache-Control"] = "no-store"
    return Response(content=body, status_code=record.response_status, headers=headers)


def claim_idempotency_key(
    db: Session,
    *,
    request: Request,
    key: str,
    body: bytes,
) -> IdempotencyClaim:
    now = utcnow()
    subject_hash = _subject_hash(request)
    request_hash = _request_hash(request, body)
    db.execute(
        delete(ApiIdempotencyRecord)
        .where(ApiIdempotencyRecord.expires_at <= now)
        .execution_options(synchronize_session=False)
    )

    lookup = (
        ApiIdempotencyRecord.subject_hash == subject_hash,
        ApiIdempotencyRecord.method == request.method,
        ApiIdempotencyRecord.path == request.url.path,
        ApiIdempotencyRecord.idempotency_key == key,
    )
    existing = db.scalar(select(ApiIdempotencyRecord).where(*lookup))
    if existing is not None:
        if existing.request_hash != request_hash:
            return IdempotencyClaim(
                error=_error_response(
                    request,
                    status_code=409,
                    detail="Idempotency key was already used with a different request.",
                )
            )
        if existing.state == "completed":
            try:
                replay = _replay_response(existing)
            except RuntimeError:
                return IdempotencyClaim(
                    error=_error_response(
                        request,
                        status_code=503,
                        detail="Stored idempotency response is temporarily unavailable.",
                    )
                )
            return IdempotencyClaim(replay=replay)
        if as_utc(existing.locked_until) > now:
            response = _error_response(
                request,
                status_code=409,
                detail="A request with this idempotency key is already in progress.",
            )
            response.headers["Retry-After"] = "1"
            return IdempotencyClaim(error=response)
        existing.locked_until = now + timedelta(seconds=settings.api_idempotency_pending_seconds)
        existing.expires_at = now + timedelta(seconds=settings.api_idempotency_retention_seconds)
        db.commit()
        return IdempotencyClaim(record=existing)

    record = ApiIdempotencyRecord(
        subject_hash=subject_hash,
        method=request.method,
        path=request.url.path,
        idempotency_key=key,
        request_hash=request_hash,
        state="pending",
        response_status=None,
        response_headers=None,
        encrypted_response_body=None,
        locked_until=now + timedelta(seconds=settings.api_idempotency_pending_seconds),
        expires_at=now + timedelta(seconds=settings.api_idempotency_retention_seconds),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return claim_idempotency_key(db, request=request, key=key, body=body)
    db.refresh(record)
    return IdempotencyClaim(record=record)


def complete_idempotency_record(
    db: Session,
    *,
    record_id,
    response_status: int,
    response_headers: dict[str, str],
    response_body: bytes,
) -> None:
    record = db.get(ApiIdempotencyRecord, record_id)
    if record is None:
        return
    record.state = "completed"
    record.response_status = response_status
    record.response_headers = {
        key: value
        for key, value in response_headers.items()
        if key.lower() in REPLAYED_RESPONSE_HEADERS
    }
    record.encrypted_response_body = _fernet().encrypt(response_body)
    record.locked_until = utcnow()
    db.commit()


def release_idempotency_record(db: Session, *, record_id) -> None:
    record = db.get(ApiIdempotencyRecord, record_id)
    if record is not None:
        db.delete(record)
        db.commit()


async def execute_idempotent_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not is_sensitive_create_request(request):
        return await call_next(request)
    raw_key = request.headers.get("Idempotency-Key")
    if raw_key is None:
        return await call_next(request)
    key = raw_key.strip()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        return _error_response(
            request,
            status_code=422,
            detail="Idempotency-Key must contain 1-255 safe characters.",
        )
    if not settings.api_idempotency_encryption_key:
        return _error_response(
            request,
            status_code=503,
            detail="API idempotency is temporarily unavailable.",
        )

    body = await request.body()
    db = SessionLocal()
    try:
        try:
            claim = claim_idempotency_key(db, request=request, key=key, body=body)
        except Exception:
            db.rollback()
            logger.exception(
                "api_idempotency_claim_failed",
                extra={"request_id": getattr(request.state, "request_id", None)},
            )
            return _error_response(
                request,
                status_code=503,
                detail="API idempotency is temporarily unavailable.",
            )
    finally:
        db.close()
    if claim.error is not None:
        return claim.error
    if claim.replay is not None:
        return claim.replay
    if claim.record is None:
        return _error_response(request, status_code=503, detail="API idempotency is unavailable.")

    try:
        downstream = await call_next(request)
        response_body = b"".join([chunk async for chunk in downstream.body_iterator])
        response = Response(
            content=response_body,
            status_code=downstream.status_code,
            headers=dict(downstream.headers),
            background=downstream.background,
        )
    except Exception:
        db = SessionLocal()
        try:
            try:
                release_idempotency_record(db, record_id=claim.record.id)
            except Exception:
                db.rollback()
                logger.exception(
                    "api_idempotency_release_failed",
                    extra={"request_id": getattr(request.state, "request_id", None)},
                )
        finally:
            db.close()
        raise

    db = SessionLocal()
    try:
        try:
            if response.status_code < 500 and response.status_code != 429:
                complete_idempotency_record(
                    db,
                    record_id=claim.record.id,
                    response_status=response.status_code,
                    response_headers=dict(response.headers),
                    response_body=response_body,
                )
            else:
                release_idempotency_record(db, record_id=claim.record.id)
        except Exception:
            db.rollback()
            logger.exception(
                "api_idempotency_completion_failed",
                extra={"request_id": getattr(request.state, "request_id", None)},
            )
            response.headers["Idempotency-Storage"] = "unavailable"
    finally:
        db.close()
    response.headers["Idempotency-Replayed"] = "false"
    response.headers["Cache-Control"] = "no-store"
    return response
