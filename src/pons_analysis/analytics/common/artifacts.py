"""Shared readers for file-based analysis evidence."""

import datetime
from collections.abc import Iterable
from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.storage.store import ArtifactStore


def utc(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.UTC).isoformat()


def int_value(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


def read_list(
    store: ArtifactStore, relative: str, model, *, required: bool = True
) -> list[Any]:
    payload = store.read_json(relative)
    if payload is None:
        if required:
            raise InvariantError(f"Missing analysis artifact: {relative}")
        return []
    return [model.model_validate(item) for item in payload]


def read_blocks(store: ArtifactStore, relatives: Iterable[str]) -> dict[int, int]:
    timestamps: dict[int, int] = {}
    for relative in relatives:
        payload = store.read_json(relative) or {}
        for key, block in payload.items():
            timestamps[int(key)] = int_value(block["timestamp"])
    return timestamps
