from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from envbasis_proxy.errors import invalid_request, operation_blocked, unsupported_operation
from envbasis_proxy.validation.common import ValidatedRequest, parse_json_body, validate_path


OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
REPO = r"[A-Za-z0-9._-]{1,100}"
NUMBER = r"[1-9][0-9]*"
REF = r"[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,512}"
REPO_ROOT = rf"repos/{OWNER}/{REPO}"

SENSITIVE_SEGMENTS = (
    "/actions/secrets",
    "/dependabot/secrets",
    "/codespaces/secrets",
    "/collaborators",
    "/deployments",
    "/hooks",
    "/keys",
    "/personal-access-tokens",
)


def _object_body(request: Request, body: bytes, *, required: bool) -> dict[str, Any] | None:
    parsed = parse_json_body(request, body, required=required)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise invalid_request("The GitHub request body must be a JSON object.")
    return parsed


def _matches(pattern: str, path: str) -> bool:
    return re.fullmatch(pattern, path) is not None


def validate_github_request(request: Request, path: str, body: bytes) -> ValidatedRequest:
    normalized = validate_path(path)
    method = request.method.upper()

    if method == "DELETE":
        raise operation_blocked("GitHub deletion operations are disabled.")
    if normalized == "graphql" or normalized.startswith("graphql/"):
        raise operation_blocked("GitHub GraphQL is disabled because mutations can hide destructive operations.")
    lowered_path = f"/{normalized.lower()}"
    if re.search(r"/environments/[^/]+/secrets(?:/|$)", lowered_path):
        raise operation_blocked("GitHub credential and secret-management operations are disabled.")
    if any(segment in lowered_path for segment in SENSITIVE_SEGMENTS):
        raise operation_blocked("GitHub credential, administrative, and sensitive operations are disabled.")
    if normalized in {"applications", "app/installations", "installation/repositories"} or normalized.startswith(
        ("applications/", "app/installations/", "user/installations/")
    ):
        raise operation_blocked("GitHub token and installation-management operations are disabled.")

    json_body: dict[str, Any] | list[Any] | None = None
    operation: str | None = None

    read_patterns = (
        (rf"{REPO_ROOT}", "repositories.get"),
        (rf"{REPO_ROOT}/contents(?:/{REF})?", "contents.read"),
        (rf"{REPO_ROOT}/issues(?:/{NUMBER})?", "issues.read"),
        (rf"{REPO_ROOT}/issues/{NUMBER}/comments(?:/{NUMBER})?", "issues.comments.read"),
        (rf"{REPO_ROOT}/pulls(?:/{NUMBER})?", "pull_requests.read"),
        (rf"{REPO_ROOT}/pulls/{NUMBER}/(?:files|commits|reviews|comments)", "pull_requests.details.read"),
        (rf"{REPO_ROOT}/commits(?:/{REF})?", "commits.read"),
        (rf"{REPO_ROOT}/branches(?:/{REF})?", "branches.read"),
        (rf"{REPO_ROOT}/git/ref/{REF}", "git_refs.read"),
        (rf"{REPO_ROOT}/commits/{REF}/check-runs", "checks.read"),
        (rf"{REPO_ROOT}/actions/runs(?:/{NUMBER})?", "actions.runs.read"),
    )
    if method == "GET":
        for pattern, candidate in read_patterns:
            if _matches(pattern, normalized):
                operation = candidate
                break
        if operation is not None:
            if body:
                raise invalid_request("GitHub GET operations do not accept a request body.")
        else:
            raise unsupported_operation("This GitHub read operation is not supported by the proxy.")

    write_patterns: tuple[tuple[str, str, str], ...] = (
        ("POST", rf"{REPO_ROOT}/issues", "issues.create"),
        ("PATCH", rf"{REPO_ROOT}/issues/{NUMBER}", "issues.update"),
        ("POST", rf"{REPO_ROOT}/issues/{NUMBER}/comments", "issues.comments.create"),
        ("PATCH", rf"{REPO_ROOT}/issues/comments/{NUMBER}", "issues.comments.update"),
        ("POST", rf"{REPO_ROOT}/pulls", "pull_requests.create"),
        ("PATCH", rf"{REPO_ROOT}/pulls/{NUMBER}", "pull_requests.update"),
        ("POST", rf"{REPO_ROOT}/pulls/{NUMBER}/reviews", "pull_requests.reviews.create"),
        ("POST", rf"{REPO_ROOT}/pulls/{NUMBER}/comments", "pull_requests.comments.create"),
        ("PUT", rf"{REPO_ROOT}/pulls/{NUMBER}/merge", "pull_requests.merge"),
        ("PUT", rf"{REPO_ROOT}/contents/{REF}", "contents.write"),
        ("POST", rf"{REPO_ROOT}/git/refs", "git_refs.create"),
        ("PATCH", rf"{REPO_ROOT}/git/refs/{REF}", "git_refs.update"),
        ("POST", rf"{REPO_ROOT}/check-runs", "checks.create"),
        ("PATCH", rf"{REPO_ROOT}/check-runs/{NUMBER}", "checks.update"),
        ("POST", rf"{REPO_ROOT}/statuses/{REF}", "statuses.create"),
        ("POST", rf"{REPO_ROOT}/actions/workflows/{REF}/dispatches", "actions.workflow.dispatch"),
    )
    if method != "GET":
        for expected_method, pattern, candidate in write_patterns:
            if method == expected_method and _matches(pattern, normalized):
                operation = candidate
                break
        if operation is None:
            raise unsupported_operation("This GitHub write operation is not supported by the proxy.")
        json_body = _object_body(request, body, required=True)
        if operation == "git_refs.update" and json_body.get("force") is True:
            raise operation_blocked("Force-updating Git references is disabled.")
        if operation == "pull_requests.merge" and "sha" in json_body and not isinstance(json_body["sha"], str):
            raise invalid_request("GitHub merge field 'sha' must be a string.")

    return ValidatedRequest(
        provider="github",
        operation=operation,
        method=method,
        upstream_path=normalized,
        body=body,
        json_body=json_body,
    )
