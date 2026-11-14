"""FIFO lot mutation and inventory reconciliation."""

import collections

from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch

from .models import Lot, _Ledger


def _add_lot(
    ledger: _Ledger, wallet: str, tokens: int, cost: int, timestamp: int
) -> None:
    if tokens < 0 or cost < 0:
        raise InvariantError("Lot amounts and costs must be non-negative")
    if tokens:
        ledger.lots[wallet].append(Lot(tokens, cost, timestamp, ledger.next_sequence))
        ledger.next_sequence += 1
        ledger.available[wallet] += tokens


def _take_lots(ledger: _Ledger, wallet: str, amount: int, *, context: str) -> int:
    """Remove ``amount`` tokens FIFO and return their exact integer cost."""
    if amount < 0:
        raise InvariantError("Disposal amount must be non-negative")
    queue = ledger.lots[wallet]
    available = ledger.available[wallet]
    if amount > available:
        raise InvariantError(
            f"{context}: {wallet} disposes {amount} tokens but holds {available}"
        )
    basis = 0
    remaining = amount
    while remaining:
        lot = queue[0]
        if lot.tokens <= remaining:
            basis += lot.cost
            remaining -= lot.tokens
            queue.popleft()
            continue
        cost = lot.cost * remaining // lot.tokens
        basis += cost
        lot.tokens -= remaining
        lot.cost -= cost
        remaining = 0
    ledger.available[wallet] = available - amount
    return basis


def _move_lots(
    ledger: _Ledger, source: str, destination: str, amount: int, *, context: str
) -> int:
    if amount < 0:
        raise InvariantError("Transfer amount must be non-negative")
    if not amount:
        return 0
    queue = ledger.lots[source]
    available = ledger.available[source]
    if amount > available:
        raise InvariantError(
            f"{context}: {source} moves {amount} tokens but holds {available}"
        )
    moved: list[Lot] = []
    moved_basis = 0
    remaining = amount
    while remaining:
        lot = queue[0]
        if lot.tokens <= remaining:
            moved.append(lot)
            moved_basis += lot.cost
            remaining -= lot.tokens
            queue.popleft()
            continue
        cost = lot.cost * remaining // lot.tokens
        moved.append(Lot(remaining, cost, lot.timestamp, lot.sequence))
        moved_basis += cost
        lot.tokens -= remaining
        lot.cost -= cost
        remaining = 0
    combined = list(ledger.lots[destination]) + moved
    combined.sort(key=lambda lot: (lot.timestamp, lot.sequence))
    ledger.lots[destination] = collections.deque(combined)
    ledger.available[source] = available - amount
    ledger.available[destination] += amount
    return moved_basis


def _reconcile(
    balances: collections.Counter[str],
    lots: dict[str, collections.deque[Lot]],
    available: collections.Counter[str],
    protocol: set[str],
    profile: Launch,
) -> None:
    for wallet in set(lots) | set(available):
        held = sum(lot.tokens for lot in lots.get(wallet, ()))
        if held != available.get(wallet, 0):
            raise InvariantError(
                f"Lot index does not reconcile for {wallet}: "
                f"{held} lots vs {available.get(wallet, 0)} tracked"
            )
    for wallet, balance in balances.items():
        if wallet == ZERO or wallet in protocol:
            continue
        held = sum(lot.tokens for lot in lots.get(wallet, ()))
        if held != balance:
            raise InvariantError(
                f"Token inventory does not reconcile for {wallet}: "
                f"{held} in FIFO lots vs {balance} transferred"
            )
    if balances[ZERO] != -profile.supply:
        raise InvariantError(
            "Observed token supply does not match the profile: "
            f"{-balances[ZERO]} != {profile.supply}"
        )
    if any(value < 0 for wallet, value in balances.items() if wallet != ZERO):
        raise InvariantError("Negative token balance in position evidence")
