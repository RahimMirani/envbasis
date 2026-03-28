from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError
from pydantic import AnyHttpUrl, BaseModel, SecretStr

from envbasis_cli.contracts import Endpoint, UserProfile, build_path


SERVICE_NAME = "envbasis-cli"
SESSION_USERNAME = "auth-session"
REFRESH_SKEW_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 5


class AuthError(RuntimeError):
    pass


class CliAuthSession(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr
    token_type: str
    expires_at: datetime
    user_id: str
    email: str


class CliAuthStartRequest(BaseModel):
    client_name: str
    device_name: str
    cli_version: str
    platform: str


class CliAuthStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_url: AnyHttpUrl
    verification_url_complete: AnyHttpUrl | None = None
    expires_in: int
    interval: int = DEFAULT_POLL_INTERVAL_SECONDS


class CliAuthTokenRequest(BaseModel):
    device_code: str


class CliAuthRefreshRequest(BaseModel):
    refresh_token: str


class CliAuthLogoutRequest(BaseModel):
    refresh_token: str


class CliAuthStatusResponse(BaseModel):
    error: str
    interval: int | None = None


class CliAuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int | None = None
    expires_at: datetime | None = None
    user: UserProfile | None = None


class CliAuthPollResult(BaseModel):
    status_code: int
    error: str | None = None
    interval: int | None = None
    session: CliAuthSession | None = None
    user: UserProfile | None = None


class AuthManager:
    def __init__(
        self,
        service_name: str = SERVICE_NAME,
        username: str = SESSION_USERNAME,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.service_name = service_name
        self.username = username
        self.timeout = timeout

    def load_session(self) -> CliAuthSession | None:
        try:
            raw_session = keyring.get_password(self.service_name, self.username)
        except KeyringError as exc:
            raise AuthError(f"Failed to read auth session from keyring: {exc}") from exc

        if not raw_session:
            return None

        try:
            payload = json.loads(raw_session)
            return CliAuthSession.model_validate(payload)
        except (ValueError, TypeError) as exc:
            raise AuthError("Stored auth session is invalid. Run envbasis login again.") from exc

    def save_session(self, session: CliAuthSession) -> None:
        payload = {
            "access_token": session.access_token.get_secret_value(),
            "refresh_token": session.refresh_token.get_secret_value(),
            "token_type": session.token_type,
            "expires_at": session.expires_at.isoformat(),
            "user_id": session.user_id,
            "email": session.email,
        }

        try:
            keyring.set_password(self.service_name, self.username, json.dumps(payload))
        except KeyringError as exc:
            raise AuthError(f"Failed to store auth session in keyring: {exc}") from exc

    def clear_session(self) -> None:
        try:
            keyring.delete_password(self.service_name, self.username)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise AuthError(f"Failed to remove auth session from keyring: {exc}") from exc

    def start_device_login(self, api_url: str, request: CliAuthStartRequest) -> CliAuthStartResponse:
        payload = self._request_json(
            api_url,
            Endpoint.CLI_AUTH_START,
            request.model_dump(),
            default_error="Could not start CLI login. Run envbasis login again.",
        )
        try:
            response = CliAuthStartResponse.model_validate(payload)
        except ValueError as exc:
            raise AuthError("Backend returned an invalid CLI login response. Run envbasis login again.") from exc

        return response.model_copy(update={"interval": self._normalize_interval(response.interval)})

    def poll_for_session(self, api_url: str, device_code: str) -> CliAuthPollResult:
        url = f"{api_url.rstrip('/')}{build_path(Endpoint.CLI_AUTH_TOKEN)}"
        body = CliAuthTokenRequest(device_code=device_code).model_dump()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request("POST", url, json=body, headers=self._json_headers())
        except httpx.HTTPError as exc:
            raise AuthError(
                f"Could not reach the EnvBasis API. Check --api-url and your network connection: {exc}"
            ) from exc

        if response.status_code == 200:
            payload = self._parse_json(response, "Backend returned an invalid CLI auth token response.")
            token_response = self._parse_token_response(payload)
            session = self._session_from_token_response(token_response)
            return CliAuthPollResult(status_code=200, session=session, user=token_response.user)

        if response.status_code in {202, 403, 404, 409, 410, 429}:
            payload = self._parse_json(response, "Backend returned an invalid CLI auth status response.")
            status = self._parse_status_response(payload)
            return CliAuthPollResult(
                status_code=response.status_code,
                error=status.error,
                interval=self._normalize_interval(status.interval),
            )

        raise AuthError(self._backend_error_message(response, "Could not complete CLI login. Run envbasis login again."))

    def refresh_session(self, api_url: str, *, session: CliAuthSession | None = None) -> CliAuthSession:
        active_session = session or self.load_session()
        if active_session is None:
            raise AuthError("You are not logged in.")

        try:
            payload = self._request_json(
                api_url,
                Endpoint.CLI_AUTH_REFRESH,
                CliAuthRefreshRequest(
                    refresh_token=active_session.refresh_token.get_secret_value()
                ).model_dump(),
                default_error="Could not refresh the current session. Run envbasis login again.",
            )
            token_response = self._parse_token_response(payload)
        except AuthError as exc:
            self._best_effort_clear_session()
            raise AuthError("Your session expired and could not be refreshed. Run envbasis login again.") from exc

        refreshed_session = self._session_from_token_response(token_response, fallback_session=active_session)
        self.save_session(refreshed_session)
        return refreshed_session

    def logout_session(self, api_url: str, *, session: CliAuthSession | None = None) -> None:
        active_session = session or self.load_session()
        if active_session is None:
            return

        self._request_json(
            api_url,
            Endpoint.CLI_AUTH_LOGOUT,
            CliAuthLogoutRequest(refresh_token=active_session.refresh_token.get_secret_value()).model_dump(),
            default_error="Could not revoke the current session.",
        )

    def get_valid_access_token(self, api_url: str, *, force_refresh: bool = False) -> str:
        session = self.load_session()
        if session is None:
            raise AuthError("You are not logged in.")

        if force_refresh or self._should_refresh(session):
            session = self.refresh_session(api_url, session=session)

        return session.access_token.get_secret_value()

    def needs_refresh(self) -> bool:
        session = self.load_session()
        return session is not None and self._should_refresh(session)

    def _request_json(
        self,
        api_url: str,
        endpoint: Endpoint,
        body: dict[str, Any],
        *,
        default_error: str,
    ) -> dict[str, Any]:
        url = f"{api_url.rstrip('/')}{build_path(endpoint)}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request("POST", url, json=body, headers=self._json_headers())
        except httpx.HTTPError as exc:
            raise AuthError(
                f"Could not reach the EnvBasis API. Check --api-url and your network connection: {exc}"
            ) from exc

        if not response.is_success:
            raise AuthError(self._backend_error_message(response, default_error))

        return self._parse_json(response, default_error)

    def _session_from_token_response(
        self,
        payload: CliAuthTokenResponse,
        *,
        fallback_session: CliAuthSession | None = None,
    ) -> CliAuthSession:
        expires_at = self._resolve_expiration(payload)
        user_id = payload.user.id if payload.user is not None else fallback_session.user_id if fallback_session else ""
        email = payload.user.email if payload.user is not None else fallback_session.email if fallback_session else ""

        if not user_id or not email:
            raise AuthError("Backend did not include the authenticated user. Run envbasis login again.")

        return CliAuthSession(
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            token_type=payload.token_type,
            expires_at=expires_at,
            user_id=user_id,
            email=email,
        )

    def _resolve_expiration(self, payload: CliAuthTokenResponse) -> datetime:
        if payload.expires_at is not None:
            expires_at = payload.expires_at
            if expires_at.tzinfo is None:
                return expires_at.replace(tzinfo=timezone.utc)
            return expires_at.astimezone(timezone.utc)
        if payload.expires_in is not None:
            return datetime.now(timezone.utc) + timedelta(seconds=payload.expires_in)
        raise AuthError("Backend did not include token expiration. Run envbasis login again.")

    @staticmethod
    def _parse_json(response: httpx.Response, default_error: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthError(default_error) from exc
        if not isinstance(payload, dict):
            raise AuthError(default_error)
        return payload

    @staticmethod
    def _parse_token_response(payload: dict[str, Any]) -> CliAuthTokenResponse:
        try:
            return CliAuthTokenResponse.model_validate(payload)
        except ValueError as exc:
            raise AuthError("Backend returned an invalid auth token payload. Run envbasis login again.") from exc

    @staticmethod
    def _parse_status_response(payload: dict[str, Any]) -> CliAuthStatusResponse:
        try:
            return CliAuthStatusResponse.model_validate(payload)
        except ValueError as exc:
            raise AuthError("Backend returned an invalid auth status payload. Run envbasis login again.") from exc

    def _best_effort_clear_session(self) -> None:
        try:
            self.clear_session()
        except AuthError:
            return

    def _should_refresh(self, session: CliAuthSession) -> bool:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=REFRESH_SKEW_SECONDS)

    @staticmethod
    def _json_headers() -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    @staticmethod
    def _normalize_interval(interval: int | None) -> int:
        if isinstance(interval, int) and interval > 0:
            return interval
        return DEFAULT_POLL_INTERVAL_SECONDS

    @staticmethod
    def _backend_error_message(response: httpx.Response, default_message: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or default_message

        if isinstance(payload, dict):
            for key in ("detail", "error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value

        return response.text or default_message


TokenStore = AuthManager
