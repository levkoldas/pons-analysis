"""Cursor pagination with loop detection and explicit completeness."""

from collections.abc import Callable
from typing import Any

from pons_analysis.core.errors import ProviderError
from pons_analysis.core.models import PageResult
from pons_analysis.storage.store import canonical


def paginate(
    fetch: Callable[[dict[str, Any], int], dict[str, Any]],
    params: dict[str, Any] | None = None,
    *,
    cap: int = 100,
    items_key: str = "items",
    cursor_key: str = "next_page_params",
    stop: Callable[[dict[str, Any]], bool] | None = None,
) -> PageResult:
    if cap < 1:
        raise ValueError("Page cap must be positive")
    base = dict(params or {})
    current = dict(base)
    seen = {canonical(current)}
    items: list[Any] = []
    cursor = None
    for page in range(cap):
        data = fetch(current, page)
        if not isinstance(data, dict) or not isinstance(data.get(items_key), list):
            raise ProviderError(f"Expected a paginated response with {items_key}")
        items.extend(data[items_key])
        if stop is not None and stop(data):
            return PageResult(items=items, complete=True, pages=page + 1)
        cursor = data.get(cursor_key)
        if cursor in (None, "", {}):
            return PageResult(items=items, complete=True, pages=page + 1)
        if cursor_key == "next_page_params":
            if not isinstance(cursor, dict):
                raise ProviderError("Expected a Blockscout cursor object")
            current = {**base, **cursor}
        else:
            current = {**base, "cursor": cursor}
        key = canonical(current)
        if key in seen:
            raise ProviderError("Repeated pagination cursor")
        seen.add(key)
    return PageResult(items=items, complete=False, pages=cap)
