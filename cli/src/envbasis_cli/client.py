from __future__ import annotations

from typing import Any

import httpx
from pydantic import TypeAdapter

from envbasis_cli.auth import AuthError
from envbasis_cli.contracts import ErrorPayload


class APIError(RuntimeError):
    def __init__(self, status_code: int, message: str, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class EnvBasisClient:
    def __init__(
        self,
        base_url: str,
        auth_manager: Any,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_manager = auth_manager
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                headers = self._build_headers()
                response = client.request(method, url, params=params, json=json_body, headers=headers)
                retried_after_refresh = False
                if response.status_code == 401 and self._supports_refresh():
                    headers = self._build_headers(force_refresh=True)
                    response = client.request(method, url, params=params, json=json_body, headers=headers)
                    retried_after_refresh = True
        except httpx.HTTPError as exc:
            raise APIError(
                0,
                "Could not reach the EnvBasis API. Check --api-url and your network connection.",
                str(exc),
            ) from exc
        except AuthError as exc:
            raise APIError(401, str(exc)) from exc
        if response.status_code == 401 and retried_after_refresh:
            self._best_effort_clear_session()
        return self._handle_response(response)

    def request_model(
        self,
        method: str,
        path: str,
        response_model: type[Any],
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        payload = self.request(method, path, params=params, json_body=json_body)
        return TypeAdapter(response_model).validate_python(payload)

    def _build_headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        token = self._get_access_token(force_refresh=force_refresh)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_access_token(self, *, force_refresh: bool = False) -> str | None:
        if hasattr(self.auth_manager, "get_valid_access_token"):
            return self.auth_manager.get_valid_access_token(self.base_url, force_refresh=force_refresh)
        if hasattr(self.auth_manager, "get"):
            return self.auth_manager.get()
        raise AuthError("No auth provider is configured.")

    def _supports_refresh(self) -> bool:
        return hasattr(self.auth_manager, "get_valid_access_token")

    def _best_effort_clear_session(self) -> None:
        if not hasattr(self.auth_manager, "clear_session"):
            return
        try:
            self.auth_manager.clear_session()
        except AuthError:
            return

    def _handle_response(self, response: httpx.Response) -> Any:
        if response.is_success:
            if not response.content:
                return None
            return response.json()

        raise self._to_error(response)

    def _to_error(self, response: httpx.Response) -> APIError:
        payload: Any | None = None
        message = self._default_message(response.status_code)

        try:
            payload = response.json()
            error_payload = ErrorPayload.model_validate(payload)
            if response.status_code == 409 and error_payload.detail:
                message = self._stringify(error_payload.detail)
            elif error_payload.detail:
                message = self._stringify(error_payload.detail)
        except (ValueError, TypeError):
            payload = response.text or None

        return APIError(response.status_code, message, payload)

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _default_message(status_code: int) -> str:
        if status_code == 401:
            return "You are not logged in."
        if status_code == 403:
            return "You do not have permission for this action."
        if status_code == 404:
            return "Project/environment/token not found."
        if status_code == 409:
            return "The request could not be completed because it conflicts with the current state."
        return f"Request failed with status code {status_code}."
