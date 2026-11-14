"""Per-wallet native cashflow primitives."""

from collections.abc import Iterable
from typing import Any


def _int(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


def _party(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("hash")
    return (value or "").lower()


def next_nonce_payment(
    wallet_transactions: Iterable[Any],
    sale_transaction: Any,
    *,
    selector: str | None = None,
) -> Any | None:
    """Return the wallet's ``nonce + 1`` transaction, optionally filtered by selector."""
    sender = getattr(sale_transaction, "from_address", None)
    if sender is None:
        sender = sale_transaction["from"]
    sender = _party(sender)
    nonce = getattr(sale_transaction, "nonce", None)
    if nonce is None:
        nonce = sale_transaction["nonce"]
    nonce = _int(nonce)
    selector = selector.lower() if selector is not None else None
    for transaction in wallet_transactions:
        if isinstance(transaction, dict):
            tx_sender = _party(transaction.get("from"))
            tx_nonce = transaction.get("nonce")
            tx_input = transaction.get("raw_input") or transaction.get("input") or ""
        else:
            tx_sender = _party(transaction.from_address)
            tx_nonce = transaction.nonce
            tx_input = transaction.input
        if tx_nonce is None:
            continue
        if tx_sender == sender and _int(tx_nonce) == nonce + 1:
            if selector is None or tx_input.lower().startswith(selector):
                return transaction
    return None


def net_cash_surplus(
    *,
    external_sales: int,
    claims: int,
    initial_buys: int,
    launch_fee: int,
    gas: int,
) -> int:
    """Wei surplus that excludes internal sweeps and rotations by construction."""
    return external_sales + claims - initial_buys - launch_fee - gas
