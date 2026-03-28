from __future__ import annotations

import platform
import time
import webbrowser

import typer

from envbasis_cli import __version__
from envbasis_cli.auth import AuthError, CliAuthPollResult, CliAuthSession, CliAuthStartRequest
from envbasis_cli.command_support import build_client, exit_for_api_error, persist_local_config, require_api_url
from envbasis_cli.client import APIError, EnvBasisClient
from envbasis_cli.context import AppContext, require_app_context
from envbasis_cli.contracts import Endpoint, UserProfile, build_path


def register(app: typer.Typer) -> None:
    @app.command("login")
    def login(ctx: typer.Context) -> None:
        app_context = require_app_context(ctx)
        api_url = require_api_url(app_context)

        try:
            start = app_context.auth_manager.start_device_login(
                api_url,
                CliAuthStartRequest(
                    client_name="envbasis-cli",
                    device_name=_detect_device_name(),
                    cli_version=__version__,
                    platform=_detect_platform(),
                ),
            )
        except AuthError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc

        approval_url = str(start.verification_url_complete or start.verification_url)
        app_context.output.info("Approve this CLI login in your browser:")
        app_context.output.write(f"Code: {start.user_code}")
        app_context.output.write(approval_url)
        _open_browser_best_effort(approval_url)

        deadline = time.monotonic() + max(start.expires_in, 1)
        poll_interval = max(start.interval, 1)

        try:
            while True:
                if time.monotonic() >= deadline:
                    raise AuthError("Login session expired. Run envbasis login again.")

                poll_result = app_context.auth_manager.poll_for_session(api_url, start.device_code)
                if poll_result.session is not None:
                    session, user = _confirm_login(api_url, poll_result)
                    app_context.auth_manager.save_session(session)
                    _persist_login_context(app_context)

                    if app_context.options.output_json:
                        app_context.output.emit_json(
                            {
                                "authenticated": True,
                                "user": user.model_dump(),
                                "api_url": app_context.resolved_api_url,
                            }
                        )
                        return

                    app_context.output.success(f"Logged in as {user.email}")
                    return

                poll_interval = _next_poll_interval(poll_result, poll_interval)
                if poll_result.status_code in {202, 429}:
                    time.sleep(poll_interval)
                    continue

                raise AuthError(_terminal_poll_error_message(poll_result))
        except AuthError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

    @app.command("logout")
    def logout(ctx: typer.Context) -> None:
        app_context = require_app_context(ctx)
        api_url = require_api_url(app_context)
        try:
            session = app_context.auth_manager.load_session()
        except AuthError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc

        if session is not None:
            try:
                app_context.auth_manager.logout_session(api_url, session=session)
            except AuthError:
                pass

        try:
            app_context.auth_manager.clear_session()
        except AuthError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc

        if app_context.options.output_json:
            app_context.output.emit_json({"authenticated": False})
            return

        app_context.output.success("Logged out")

    @app.command("whoami")
    def whoami(ctx: typer.Context) -> None:
        app_context = require_app_context(ctx)
        try:
            session = app_context.auth_manager.load_session()
        except AuthError as exc:
            app_context.output.error(str(exc))
            raise typer.Exit(code=1) from exc

        if session is None:
            app_context.output.error("You are not logged in.")
            raise typer.Exit(code=1)

        client = build_client(app_context)

        try:
            user = client.request_model("GET", build_path(Endpoint.AUTH_ME), UserProfile)
        except APIError as exc:
            raise exit_for_api_error(app_context, exc) from exc

        if app_context.options.output_json:
            app_context.output.emit_json(user.model_dump())
            return

        app_context.output.table(
            "Authenticated User",
            ["Field", "Value"],
            [["id", user.id], ["email", user.email]],
        )


def _persist_login_context(app_context: AppContext) -> None:
    if not app_context.options.api_url:
        return

    persist_local_config(app_context, api_base_url=app_context.options.api_url)


def _confirm_login(api_url: str, poll_result: CliAuthPollResult) -> tuple[CliAuthSession, UserProfile]:
    assert poll_result.session is not None
    user = _validate_backend_session(api_url, poll_result.session.access_token.get_secret_value())
    session = poll_result.session.model_copy(update={"user_id": user.id, "email": user.email})
    return session, user


def _validate_backend_session(api_url: str, access_token: str) -> UserProfile:
    class _StaticTokenAuth:
        def __init__(self, token: str) -> None:
            self.token = token

        def get(self) -> str:
            return self.token

    client = EnvBasisClient(api_url, _StaticTokenAuth(access_token))
    return client.request_model("GET", build_path(Endpoint.AUTH_ME), UserProfile)


def _detect_device_name() -> str:
    hostname = platform.node().strip()
    return hostname or "Unknown device"


def _detect_platform() -> str:
    system_name = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    return f"{system_name}-{machine}"


def _open_browser_best_effort(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        return


def _next_poll_interval(poll_result: CliAuthPollResult, current_interval: int) -> int:
    next_interval = poll_result.interval or current_interval
    if poll_result.status_code == 429:
        return max(current_interval + 1, next_interval)
    return max(next_interval, 1)


def _terminal_poll_error_message(poll_result: CliAuthPollResult) -> str:
    error = poll_result.error or "login_failed"
    messages = {
        "access_denied": "Access denied. Run envbasis login again.",
        "expired_token": "Login session expired. Run envbasis login again.",
        "already_used": "This login session was already used. Run envbasis login again.",
        "invalid_device_code": "The login session is invalid. Run envbasis login again.",
    }
    return messages.get(error, f"{error}. Run envbasis login again.")
