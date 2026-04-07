from __future__ import annotations

import html
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_text_invite_email(*, invite_url: str, project_name: str, inviter_email: str | None) -> str:
    inviter_line = f"\n{inviter_email} invited you to collaborate.\n" if inviter_email else "\n"
    return (
        f"You are invited to join the EnvBasis project \"{project_name}\".{inviter_line}\n"
        f"Open this link to accept or decline:\n{invite_url}\n"
    )


def _build_html_invite_email(*, invite_url: str, project_name: str, inviter_email: str | None) -> str:
    safe_project_name = html.escape(project_name)
    safe_invite_url = html.escape(invite_url, quote=True)
    inviter_copy = (
        f'<p style="margin:0 0 24px; color:#d4d4d8; font-size:16px; line-height:1.6;">'
        f'<strong style="color:#ffffff;">{html.escape(inviter_email)}</strong> invited you to collaborate on '
        f'<strong style="color:#ffffff;">{safe_project_name}</strong> in EnvBasis.</p>'
        if inviter_email
        else f'<p style="margin:0 0 24px; color:#d4d4d8; font-size:16px; line-height:1.6;">'
        f'You have been invited to collaborate on <strong style="color:#ffffff;">{safe_project_name}</strong> in EnvBasis.</p>'
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
  <body style="margin:0; padding:0; background:#060606; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; color:#ffffff;">
    <div style="padding:32px 16px; background:linear-gradient(180deg, #0a0a0a 0%, #060606 100%);">
      <div style="max-width:600px; margin:0 auto; background:#111111; border:1px solid #242424; border-radius:24px; overflow:hidden; box-shadow:0 20px 60px rgba(0,0,0,0.45);">
        <div style="padding:32px 32px 8px;">
          <div style="display:inline-block; padding:8px 14px; border-radius:999px; background:#1a1a1a; border:1px solid #2d2d2d; color:#fafafa; font-size:12px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase;">
            EnvBasis
          </div>
        </div>
        <div style="padding:8px 32px 40px;">
          <h1 style="margin:0 0 16px; font-size:36px; line-height:1.1; color:#ffffff; letter-spacing:-0.03em;">
            You're invited
          </h1>
          {inviter_copy}
          <a
            href="{safe_invite_url}"
            style="display:inline-block; padding:14px 22px; border-radius:14px; background:#ffffff; color:#090909; text-decoration:none; font-size:15px; font-weight:700;"
          >
            Open EnvBasis &rarr;
          </a>
          <p style="margin:28px 0 8px; color:#a1a1aa; font-size:13px; line-height:1.6;">
            If the button does not work, paste this link into your browser:
          </p>
          <p style="margin:0; word-break:break-all;">
            <a href="{safe_invite_url}" style="color:#93c5fd; font-size:13px; line-height:1.7; text-decoration:underline;">
              {safe_invite_url}
            </a>
          </p>
        </div>
      </div>
    </div>
  </body>
</html>
"""


def send_project_invite_email(
    *,
    to_email: str,
    invite_url: str,
    project_name: str,
    inviter_email: str | None = None,
) -> bool:
    """Send invite email when SMTP is configured; otherwise log and return False."""
    subject = "You are invited to an EnvBasis project"
    body = _build_text_invite_email(
        invite_url=invite_url,
        project_name=project_name,
        inviter_email=inviter_email,
    )
    html_body = _build_html_invite_email(
        invite_url=invite_url,
        project_name=project_name,
        inviter_email=inviter_email,
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
    msg.add_alternative(html_body, subtype="html")

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
