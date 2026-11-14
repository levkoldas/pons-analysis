"""Native-ETH accounting over address histories and fixed windows.

Rows may be Blockscout v2 mappings (``from``/``to`` objects, ``value``,
``gas_used``, ``gas_price``, ``result``) or validated ``RpcTransaction`` /
``RpcReceipt`` models. Amounts stay integer wei; callers convert for display.
A reverted transaction refunds its value but still burns gas.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def _party(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("hash")
    return (value or "").lower()


def _sender(row: Any) -> str:
    if hasattr(row, "from_address"):
        return _party(row.from_address)
    if isinstance(row, dict):
        return _party(row.get("from"))
    return _party(getattr(row, "from_", None))


def _recipient(row: Any) -> str:
    if hasattr(row, "to"):
        return _party(row.to)
    if isinstance(row, dict):
        return _party(row.get("to"))
    return ""


def _integer(row: Any, *names: str) -> int:
    for name in names:
        value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        if value is not None:
            if isinstance(value, str):
                return int(value, 16) if value.startswith("0x") else int(value)
            return int(value)
    return 0


def _block(row: Any) -> int:
    return _integer(row, "block_number", "blockNumber")


def _value(row: Any) -> int:
    return _integer(row, "value")


def _gas(row: Any) -> int:
    return _integer(row, "gas_used", "gasUsed") * _integer(row, "gas_price", "gasPrice")


def _succeeded(row: Any) -> bool:
    if isinstance(row, dict):
        result = row.get("result")
        if isinstance(result, str):
            lowered = result.lower()
            if lowered in ("success", "ok"):
                return True
            if lowered in ("error", "failed", "reverted"):
                return False
        if "success" in row:
            return bool(row["success"])
        status = row.get("status")
        if status is not None:
            if isinstance(status, str):
                lowered = status.lower()
                if lowered in ("ok", "success"):
                    return True
                if lowered in ("error", "failed", "reverted"):
                    return False
                try:
                    return int(status, 16) == 1
                except ValueError:
                    return False
            return int(status) == 1
        return row.get("block_number") is not None
    if hasattr(row, "succeeded"):
        return bool(row.succeeded)
    if hasattr(row, "status"):
        status = row.status
        return (int(status, 16) if isinstance(status, str) else int(status)) == 1
    # A mined transaction without a receipt has no status marker; every
    # transaction returned by eth_getTransactionByHash is already included.
    return getattr(row, "block_number", None) is not None


def _tx_hash(row: Any) -> str:
    if hasattr(row, "transaction_hash"):
        return row.transaction_hash
    if isinstance(row, dict):
        return (
            row.get("transaction_hash")
            or row.get("transactionHash")
            or row.get("hash")
            or ""
        )
    return ""


def dedupe_internal_transfers(rows: Iterable[Any]) -> list[Any]:
    """Collapse the same internal transfer returned on both party pages."""
    unique = {}
    for row in rows:
        key = (
            _tx_hash(row),
            _integer(row, "index"),
            _sender(row),
            _recipient(row),
            str(_value(row)),
            row.get("type") if isinstance(row, dict) else getattr(row, "type", None),
        )
        unique.setdefault(key, row)
    return list(unique.values())


def wallet_balance_sheet(
    transactions: Iterable[Any], internal: Iterable[Any], address: str
) -> dict[str, Any]:
    address = address.lower()
    sheet: dict[str, Any] = dict(
        address=address,
        ext_in=0,
        ext_out=0,
        int_in=0,
        int_out=0,
        gas=0,
        ntx=0,
        nint=0,
    )
    for tx in transactions:
        sender, recipient = _sender(tx), _recipient(tx)
        value = _value(tx) if _succeeded(tx) else 0
        if sender == address:
            sheet["gas"] += _gas(tx)
            sheet["ntx"] += 1
            if recipient != address:
                sheet["ext_out"] += value
        elif recipient == address:
            sheet["ext_in"] += value
    for row in dedupe_internal_transfers(internal):
        if not _succeeded(row):
            continue
        sender, recipient = _sender(row), _recipient(row)
        value = _value(row)
        sheet["nint"] += 1
        if sender == address and recipient != address:
            sheet["int_out"] += value
        elif recipient == address and sender != address:
            sheet["int_in"] += value
    sheet["in"] = sheet["ext_in"] + sheet["int_in"]
    sheet["out"] = sheet["ext_out"] + sheet["int_out"]
    sheet["net"] = sheet["in"] - sheet["out"] - sheet["gas"]
    return sheet


def balance_history(
    transactions: Iterable[Any], internal: Iterable[Any], address: str
) -> dict[str, Any]:
    """Chronological balance series that charges gas exactly once per sender tx."""
    address = address.lower()
    events, sequence = [], 0
    for tx in transactions:
        sender, recipient = _sender(tx), _recipient(tx)
        gas = _gas(tx) if sender == address else 0
        value = _value(tx) if _succeeded(tx) else 0
        if sender == address:
            if recipient != address:
                direction, moved = "out", value
            else:
                direction, moved = "gas", 0
            events.append(
                (
                    _block(tx),
                    1,
                    sequence,
                    direction,
                    recipient,
                    moved,
                    gas,
                    _tx_hash(tx),
                )
            )
            sequence += 1
        if recipient == address and sender != address:
            events.append(
                (_block(tx), 0, sequence, "in", sender, value, 0, _tx_hash(tx))
            )
            sequence += 1
    for row in dedupe_internal_transfers(internal):
        if not _succeeded(row):
            continue
        sender, recipient = _sender(row), _recipient(row)
        value = _value(row)
        if sender == address and recipient != address:
            events.append(
                (_block(row), 1, sequence, "out", recipient, value, 0, _tx_hash(row))
            )
            sequence += 1
        elif recipient == address and sender != address:
            events.append(
                (_block(row), 0, sequence, "in", sender, value, 0, _tx_hash(row))
            )
            sequence += 1
    events.sort(key=lambda event: event[:3])

    running, history = 0, []
    peak = trough = (None, 0)
    for block, _, _, direction, counterparty, value, gas, tx_hash in events:
        running += value if direction == "in" else -(value + gas)
        history.append(
            dict(
                block=block,
                direction=direction,
                counterparty=counterparty,
                value=value,
                gas=gas,
                balance=running,
                tx_hash=tx_hash,
            )
        )
        if running > peak[1]:
            peak = (block, running)
        if running < trough[1]:
            trough = (block, running)
    return dict(
        address=address, events=history, peak=peak, trough=trough, final=running
    )


def flow_statement(
    transactions: Iterable[Any],
    internal: Iterable[Any],
    *,
    members: Iterable[str],
    start_block: int | None = None,
    balances: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Set-classified ETH flow with external legs and window totals."""
    members = {address.lower() for address in members}
    balances = {
        address.lower(): int(value) for address, value in (balances or {}).items()
    }
    net = defaultdict(int)
    gas = defaultdict(int)
    inflow_by = defaultdict(int)
    outflow_by = defaultdict(int)
    legs = defaultdict(int)
    internal_legs = 0
    for tx in transactions:
        block = _block(tx)
        if start_block is not None and block < start_block:
            continue
        sender, recipient = _sender(tx), _recipient(tx)
        value = _value(tx) if _succeeded(tx) else 0
        fee = _gas(tx) if sender in members else 0
        if sender in members:
            net[sender] -= value + fee
            gas[sender] += fee
            outflow_by[sender] += value
        if recipient in members:
            net[recipient] += value
            inflow_by[recipient] += value
        if value and (sender in members) != (recipient in members):
            direction = "in" if recipient in members else "out"
            counterparty = sender if direction == "in" else recipient
            method = (
                tx.get("method")
                if isinstance(tx, dict)
                else getattr(tx, "method", None)
            )
            legs[(direction, counterparty, method or "transfer")] += value
    for row in dedupe_internal_transfers(internal):
        if not _succeeded(row):
            continue
        block = _block(row)
        if start_block is not None and block < start_block:
            continue
        sender, recipient = _sender(row), _recipient(row)
        value = _value(row)
        if sender in members:
            net[sender] -= value
            outflow_by[sender] += value
            if recipient in members:
                internal_legs += value
        if recipient in members:
            net[recipient] += value
            inflow_by[recipient] += value
        if value and (sender in members) != (recipient in members):
            direction = "in" if recipient in members else "out"
            counterparty = sender if direction == "in" else recipient
            kind = (
                row.get("type") if isinstance(row, dict) else getattr(row, "type", "")
            )
            legs[(direction, counterparty, f"internal:{kind or ''}")] += value

    rows, start_total = [], 0
    for address in sorted(members):
        balance = balances.get(address)
        row = dict(
            address=address,
            inflow=inflow_by[address],
            outflow=outflow_by[address],
            flow=net[address],
            gas=gas[address],
            balance=balance,
        )
        if balance is not None:
            row["start_balance"] = balance - net[address]
            start_total += balance - net[address]
        rows.append(row)
    inflow = sum(
        value for (direction, _, _), value in legs.items() if direction == "in"
    )
    outflow = sum(
        value for (direction, _, _), value in legs.items() if direction == "out"
    )
    gas_total = sum(gas.values())
    net_flow = inflow - outflow - gas_total
    totals = dict(
        inflow=inflow,
        outflow=outflow,
        gas=gas_total,
        internal=internal_legs,
        net_flow=net_flow,
    )
    if balances:
        balance_now = sum(balances.values())
        totals["balance_now"] = balance_now
        totals["residual"] = net_flow - (balance_now - start_total)
    return dict(
        rows=rows,
        legs=[
            dict(direction=direction, counterparty=party, method=method, value=value)
            for (direction, party, method), value in sorted(legs.items())
        ],
        totals=totals,
    )


def reconcile_balances(sheets: dict[str, dict], balances: dict[str, int]) -> int:
    mismatches = []
    for address, sheet in sheets.items():
        expected = balances.get(address)
        if expected is not None and sheet["net"] != int(expected):
            mismatches.append((address, sheet["net"], int(expected)))
    if mismatches:
        detail = ", ".join(
            f"{address}: {actual} != {expected}"
            for address, actual, expected in mismatches
        )
        raise ValueError(f"Balance history does not reconcile: {detail}")
    return len([address for address in sheets if address in balances])
