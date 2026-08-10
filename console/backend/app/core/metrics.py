from __future__ import annotations

from collections import defaultdict
from threading import Lock


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_sums: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._error_counts: dict[tuple[str, str, int], int] = defaultdict(int)

    def observe(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        method = method.upper()
        duration_seconds = max(duration_seconds, 0.0)
        with self._lock:
            self._request_counts[(method, route, status_code)] += 1
            self._duration_sums[(method, route)] += duration_seconds
            self._duration_counts[(method, route)] += 1
            if status_code >= 400:
                self._error_counts[(method, route, status_code)] += 1

    def render_prometheus(self) -> str:
        with self._lock:
            request_counts = dict(self._request_counts)
            duration_sums = dict(self._duration_sums)
            duration_counts = dict(self._duration_counts)
            error_counts = dict(self._error_counts)

        lines = [
            "# HELP envbasis_http_requests_total Total HTTP requests.",
            "# TYPE envbasis_http_requests_total counter",
        ]
        for (method, route, status_code), count in sorted(request_counts.items()):
            labels = (
                f'method="{_escape_label(method)}",'
                f'route="{_escape_label(route)}",status="{status_code}"'
            )
            lines.append(f"envbasis_http_requests_total{{{labels}}} {count}")

        lines.extend(
            [
                "# HELP envbasis_http_request_duration_seconds HTTP request duration.",
                "# TYPE envbasis_http_request_duration_seconds summary",
            ]
        )
        for (method, route), duration_sum in sorted(duration_sums.items()):
            labels = f'method="{_escape_label(method)}",route="{_escape_label(route)}"'
            lines.append(
                f"envbasis_http_request_duration_seconds_sum{{{labels}}} {duration_sum:.9f}"
            )
            lines.append(
                f"envbasis_http_request_duration_seconds_count{{{labels}}} "
                f"{duration_counts[(method, route)]}"
            )

        lines.extend(
            [
                "# HELP envbasis_http_errors_total Total HTTP responses with status 4xx or 5xx.",
                "# TYPE envbasis_http_errors_total counter",
            ]
        )
        for (method, route, status_code), count in sorted(error_counts.items()):
            labels = (
                f'method="{_escape_label(method)}",'
                f'route="{_escape_label(route)}",status="{status_code}"'
            )
            lines.append(f"envbasis_http_errors_total{{{labels}}} {count}")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._request_counts.clear()
            self._duration_sums.clear()
            self._duration_counts.clear()
            self._error_counts.clear()


request_metrics = RequestMetrics()
