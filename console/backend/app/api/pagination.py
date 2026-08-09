from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from fastapi import Response


T = TypeVar("T")
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 200


def validate_pagination(*, limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"Pagination limit must be between 1 and {MAX_PAGE_LIMIT}.")
    if offset < 0:
        raise ValueError("Pagination offset cannot be negative.")


def paginate_items(
    items: Sequence[T],
    *,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
    response: Response | None = None,
) -> list[T]:
    validate_pagination(limit=limit, offset=offset)
    total = len(items)
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
    return list(items[offset : offset + limit])
