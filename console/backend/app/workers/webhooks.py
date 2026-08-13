from __future__ import annotations

import logging
import signal
import time

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.webhooks import process_due_webhook_deliveries


logger = logging.getLogger(__name__)
_stopping = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stopping
    _stopping = True


def run_worker() -> None:
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    logger.info("Webhook worker started.")

    while not _stopping:
        db = SessionLocal()
        try:
            processed = process_due_webhook_deliveries(db)
            db.commit()
        except Exception:
            db.rollback()
            processed = 0
            logger.exception("Webhook worker batch failed.")
        finally:
            db.close()

        if processed == 0:
            time.sleep(settings.webhook_worker_poll_seconds)

    logger.info("Webhook worker stopped.")


if __name__ == "__main__":
    configure_logging()
    run_worker()
