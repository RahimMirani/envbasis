from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from app.core.config import settings


STRUCTURED_FIELDS = (
    "request_id",
    "method",
    "path",
    "route",
    "status_code",
    "duration_ms",
    "client_ip",
    "rate_limit_rule",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            # Exception messages can contain SQL parameters, URLs, or provider
            # responses. Record the class for correlation without copying those
            # potentially sensitive values into centralized logs.
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level))

    handler = next(
        (candidate for candidate in root.handlers if getattr(candidate, "_envbasis", False)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler._envbasis = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    if settings.log_json:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
