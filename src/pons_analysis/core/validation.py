"""Independent consistency checks across events, receipts, and ledgers."""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr

ZERO = "0x" + "0" * 40


def _field(log: Any, name: str) -> Any:
    if isinstance(log, dict):
        return log[name]
    attribute = {
        "transactionHash": "transaction_hash",
        "logIndex": "log_index",
        "blockNumber": "block_number",
        "transactionIndex": "transaction_index",
    }.get(name, name)
    return getattr(log, attribute)


def _log_index(log: Any) -> int:
    value = _field(log, "logIndex")
    return int(value, 16) if isinstance(value, str) else int(value)


def reconcile_events(logs: Iterable[Any], receipts: Iterable[Any]) -> dict[str, int]:
    """Reject missing, duplicate, failed, removed, or altered mined events."""
    receipt_map = {}
    for receipt in receipts:
        receipt_map[_field(receipt, "transactionHash")] = receipt
    seen: set[tuple[str, int]] = set()
    indexes: dict[str, dict[int, Any]] = {}
    for log in logs:
        tx_hash = _field(log, "transactionHash")
        key = (tx_hash, _log_index(log))
        removed = (
            log.get("removed", False)
            if isinstance(log, dict)
            else getattr(log, "removed", False)
        )
        if key in seen or removed:
            raise InvariantError("Duplicate or removed event in snapshot")
        seen.add(key)
        receipt = receipt_map.get(tx_hash)
        if receipt is None:
            raise InvariantError("Missing or failed receipt for event")
        raw_status = _field(receipt, "status")
        status = int(raw_status, 16) if isinstance(raw_status, str) else int(raw_status)
        if status != 1:
            raise InvariantError("Missing or failed receipt for event")
        if tx_hash not in indexes:
            indexes[tx_hash] = {_log_index(row): row for row in _field(receipt, "logs")}
        other = indexes[tx_hash].get(key[1])
        for name in (
            "address",
            "data",
            "topics",
            "transactionHash",
            "transactionIndex",
        ):
            if other is None or _field(other, name) != _field(log, name):
                raise InvariantError("Event differs from its transaction receipt")
    return {"events": len(seen), "transactions": len(indexes)}


def transfer_ledger(logs: Iterable[Any]) -> Counter:
    balances: Counter[str] = Counter()
    for log in logs:
        topics = _field(log, "topics")
        sender, recipient = (addr(topic) for topic in topics[1:3])
        amount = int(_field(log, "data"), 16)
        balances[sender] -= amount
        balances[recipient] += amount
    if any(value < 0 for address, value in balances.items() if address != ZERO):
        raise InvariantError("Negative token balance: transfer history is incomplete")
    if sum(balances.values()) != 0:
        raise InvariantError("Transfer ledger does not conserve token units")
    return balances


def reconcile_token_balances(
    ledger: dict[str, int],
    balances: dict[str, int],
    *,
    tolerance: int = 0,
) -> int:
    mismatches = [
        (address, ledger.get(address, 0), expected)
        for address, expected in balances.items()
        if abs(ledger.get(address, 0) - expected) > tolerance
    ]
    if mismatches:
        detail = ", ".join(
            f"{address}: {actual} != {expected}"
            for address, actual, expected in mismatches
        )
        raise InvariantError(f"Token balances do not reconcile: {detail}")
    return len(balances)


def curve_conservation(
    buys: int,
    sells: int,
    *,
    fees: int = 0,
    taxes: int = 0,
    tracked_quote: int,
    tolerance: int = 0,
) -> int:
    residual = buys - sells - fees - taxes
    if abs(residual - tracked_quote) > tolerance:
        raise InvariantError(
            f"Curve quote balance does not reconcile: {residual} != {tracked_quote}"
        )
    return residual


def reconcile_state_changes(
    expected: dict[str, int],
    changes: dict[str, int],
    *,
    tolerance: int = 0,
) -> int:
    """Match expected native deltas (address -> wei) against explorer deltas."""
    mismatches = [
        (address, expected_value, changes.get(address, 0))
        for address, expected_value in expected.items()
        if abs(expected_value - changes.get(address, 0)) > tolerance
    ]
    if mismatches:
        detail = ", ".join(
            f"{address}: {actual} != {expected}"
            for address, actual, expected in mismatches
        )
        raise InvariantError(f"Native balance changes do not reconcile: {detail}")
    return len(expected)
