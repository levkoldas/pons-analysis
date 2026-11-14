"""Small readers for heterogeneous JSON/CSV rows."""

from typing import Any


def row_int(row: Any, *names: str, default: int = 0) -> int:
    for name in names:
        value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        if value is None:
            continue
        if isinstance(value, str):
            return int(value, 16) if value.startswith("0x") else int(value)
        return int(value)
    return default


def row_hash(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("hash") or row.get("transaction_hash") or "")
    return str(getattr(row, "hash", "") or getattr(row, "transaction_hash", ""))
