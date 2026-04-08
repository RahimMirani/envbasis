from __future__ import annotations

import html
import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin

from app.core.config import settings

logger = logging.getLogger(__name__)
INLINE_LOGO_CID = "envbasis-logo"
LOCAL_LOGO_PATH = Path(__file__).resolve().parents[3] / "frontend" / "public" / "envbasis-logo.png"


def _build_text_invite_email(*, invite_url: str, project_name: str, inviter_email: str | None) -> str:
    inviter_line = f"\n{inviter_email} invited you to collaborate.\n" if inviter_email else "\n"
    return (
        f"You are invited to join the EnvBasis project \"{project_name}\".{inviter_line}\n"
        f"Open this link to accept or decline:\n{invite_url}\n"
    )


def _invite_logo_url() -> str:
    if settings.invite_logo_url:
        return settings.invite_logo_url
    return urljoin(settings.invite_app_base_url.rstrip("/") + "/", "envbasis-logo.png")


def _invite_logo_src() -> str:
    if LOCAL_LOGO_PATH.exists():
        return f"cid:{INLINE_LOGO_CID}"
    return _invite_logo_url()


def _attach_inline_logo(msg: EmailMessage) -> None:
    if not LOCAL_LOGO_PATH.exists():
        return

    with LOCAL_LOGO_PATH.open("rb") as logo_file:
        logo_bytes = logo_file.read()

    mime_type, _ = mimetypes.guess_type(str(LOCAL_LOGO_PATH))
    maintype, subtype = (mime_type or "image/png").split("/", 1)
    html_part = msg.get_body(("html",))
    if html_part is None:
        return
    html_part.add_related(
        logo_bytes,
        maintype=maintype,
        subtype=subtype,
        cid=f"<{INLINE_LOGO_CID}>",
        filename=LOCAL_LOGO_PATH.name,
        disposition="inline",
    )


def _build_html_invite_email(*, invite_url: str, project_name: str, inviter_email: str | None) -> str:
    safe_project_name = html.escape(project_name)
    safe_invite_url = html.escape(invite_url, quote=True)
    safe_logo_src = html.escape(_invite_logo_src(), quote=True)
    inviter_copy = (
        f'<strong style="font-weight:600; color:#ffffff;">{html.escape(inviter_email)}</strong> invited you to join '
        f'<strong style="font-weight:600; color:#ffffff;">{safe_project_name}</strong> on EnvBasis.'
        if inviter_email
        else f'You have been invited to join <strong style="font-weight:600; color:#ffffff;">{safe_project_name}</strong> on EnvBasis.'
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
  <body style="margin:0; padding:0; background:#020202; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; color:#ffffff;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%; background:#020202;">
      <tr>
        <td align="center" style="padding:48px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:520px; width:100%;">
            <!-- Logo -->
            <tr>
              <td align="center" style="padding:0 0 40px 0;">
                <img src="{safe_logo_src}" alt="EnvBasis" width="96" height="96" style="display:block; width:96px; height:96px; border:0; outline:none; text-decoration:none;" />
              </td>
            </tr>
            <!-- Card -->
            <tr>
              <td style="background:#0d0d0d; border:1px solid #1f1f1f; border-radius:20px; padding:44px 40px;">
                <h1 style="margin:0 0 12px; font-size:28px; line-height:1.15; font-weight:600; color:#ffffff; letter-spacing:-0.02em;">
                  You're invited
                </h1>
                <p style="margin:0 0 32px; font-size:15px; line-height:1.7; color:#a1a1aa;">
                  {inviter_copy}
                </p>
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 20px;">
                  <tr>
                    <td style="border-radius:10px; background:#ffffff;">
                      <a href="{safe_invite_url}" style="display:inline-block; padding:13px 22px; font-size:14px; line-height:1; font-weight:600; color:#0a0a0a; text-decoration:none; letter-spacing:0.01em;">
                        Accept invitation
                      </a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0; font-size:12px; line-height:1.7; word-break:break-all;">
                  <a href="{safe_invite_url}" style="color:#52525b; text-decoration:underline;">
                    {safe_invite_url}
                  </a>
                </p>
              </td>
            </tr>
            <!-- Footer -->
            <tr>
              <td style="padding:24px 4px 0; font-size:12px; line-height:1.6; color:#52525b; text-align:center;">
                Sent for project <strong style="font-weight:500; color:#71717a;">{safe_project_name}</strong> &middot;
                <a href="{safe_invite_url}" style="color:#71717a; text-decoration:underline;">open link</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
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
    _attach_inline_logo(msg)

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
