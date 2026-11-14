"""Atomic sell/rebuy rotation detection for curve-phase trades."""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from pons_analysis.core.evm import addr


def detect_rotations(
    trades: Iterable[dict[str, Any]],
    transactions: dict[str, Any],
    *,
    router: str,
    roots: Iterable[str] = (),
) -> dict[str, Any]:
    """Find transactions that sell and immediately rebuy the same quote value.

    ``trades`` rows need ``tx_hash``, ``wallet``, ``side``, ``quote_raw`` and a
    sort key (``block``, ``tx_index``, ``log_index``). A rotation has exactly
    one sell and one buy with equal quote amounts, no attached ETH, and a
    router destination. Depth propagates from ``roots`` in O(rotations).
    """
    by_tx = defaultdict(list)
    for trade in trades:
        by_tx[trade["tx_hash"]].append(trade)
    rotations = []
    for tx_hash, rows in by_tx.items():
        if len(rows) != 2:
            continue
        rows.sort(key=lambda row: (row.get("block", 0), row.get("log_index", 0)))
        sell, buy = rows
        if sell["side"] != "sell" or buy["side"] != "buy":
            continue
        if int(sell["quote_raw"]) != int(buy["quote_raw"]):
            continue
        transaction = transactions.get(tx_hash)
        if transaction is None:
            continue
        to = getattr(transaction, "to", None) or (
            transaction.get("to") if isinstance(transaction, dict) else None
        )
        value = getattr(transaction, "value", None)
        if value is None and isinstance(transaction, dict):
            value = transaction.get("value", 0)
        sender = getattr(transaction, "from_address", None) or (
            transaction.get("from") if isinstance(transaction, dict) else None
        )
        if not to or addr(to) != addr(router) or int(value or 0) != 0:
            continue
        sender_address = addr(sender) if sender else ""
        rotations.append(
            dict(
                tx_hash=tx_hash,
                block=sell.get("block"),
                tx_index=sell.get("tx_index"),
                log_index=sell.get("log_index"),
                source_wallet=sell["wallet"],
                destination_wallet=buy["wallet"],
                sender=sender_address,
                quote_raw=str(sell["quote_raw"]),
                quote_eth=int(sell["quote_raw"]) / 10**18,
            )
        )
    rotations.sort(
        key=lambda row: (row["block"] or 0, row["tx_index"] or 0, row["log_index"] or 0)
    )

    depth = {addr(root): 0 for root in roots}
    changed = True
    while changed:
        changed = False
        for rotation in rotations:
            source = rotation["source_wallet"]
            if source in depth:
                destination = rotation["destination_wallet"]
                candidate = depth[source] + 1
                if destination not in depth or candidate < depth[destination]:
                    depth[destination] = candidate
                    changed = True
    for rotation in rotations:
        rotation["source_depth"] = depth.get(rotation["source_wallet"])
        rotation["destination_depth"] = depth.get(rotation["destination_wallet"])
    return {"rotations": rotations, "depth": depth}
