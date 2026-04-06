from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_project_invite_email(
    *,
    to_email: str,
    invite_url: str,
    project_name: str,
    inviter_email: str | None = None,
) -> bool:
    """Send invite email when SMTP is configured; otherwise log and return False."""
    subject = "You are invited to an EnvBasis project"
    inviter_line = f"\n{inviter_email} invited you to collaborate.\n" if inviter_email else "\n"
    body = (
        f"You are invited to join the EnvBasis project \"{project_name}\".{inviter_line}\n"
        f"Open this link to accept or decline:\n{invite_url}\n"
    )

    if not settings.invite_smtp_host:
        logger.info(
            "Invite email (no SMTP configured; not sent). to=%s url=%s",
            to_email,
            invite_url,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.invite_from_email or settings.invite_smtp_user or "noreply@envbasis.local"
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.invite_smtp_host, settings.invite_smtp_port) as smtp:
            if settings.invite_smtp_use_tls:
                smtp.starttls()
            if settings.invite_smtp_user and settings.invite_smtp_password:
                smtp.login(settings.invite_smtp_user, settings.invite_smtp_password)
            smtp.send_message(msg)
    except OSError as exc:
        logger.warning("Invite email failed: %s", exc, exc_info=True)
        return False

    return True
