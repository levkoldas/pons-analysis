"""Transaction-scoped router and transfer-path matching."""

import collections

from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr
from pons_analysis.core.models import RpcLog


def _match_transfer(
    logs: list[RpcLog],
    *,
    sender: str | None = None,
    recipient: str | None = None,
    amount: int,
) -> RpcLog | None:
    matches = [
        log
        for log in logs
        if (sender is None or addr(log.topics[1]) == sender)
        and (recipient is None or addr(log.topics[2]) == recipient)
        and int(log.data, 16) == amount
    ]
    if len(matches) > 1:
        raise InvariantError(
            f"Ambiguous token transfer for {amount} units from {sender} to {recipient}"
        )
    return matches[0] if matches else None


def _resolve_endpoint(
    outgoing: dict[tuple[str, str, int], list[tuple[str, RpcLog]]],
    incoming: dict[tuple[str, str, int], list[tuple[str, RpcLog]]],
    trade_leg: RpcLog,
    *,
    side: str,
    protocol: set[str],
    amount: int,
) -> tuple[str, list[RpcLog]]:
    """Follow router/hook transfer paths to the wallet that owns the trade leg.

    A bonding-curve sell routed through an aggregator can traverse several
    intermediary hops before reaching the user. The curve event names the
    router adjacent to the curve, so the economic seller is the non-protocol
    source reached by walking matching token inflows backwards. Buys are
    symmetric. Returns ``(wallet, path)`` where ``path`` contains every transfer
    log that must be skipped by the position replay; ``wallet`` is the zero
    address when the leg is protocol-internal or has no matching path.
    """
    if side == "buy":
        start = addr(trade_leg.topics[2])
        adjacency = outgoing
    else:
        start = addr(trade_leg.topics[1])
        adjacency = incoming
    frontier = collections.deque([(start, [])])
    visited = {start}
    endpoints: list[tuple[str, list[RpcLog]]] = []
    while frontier:
        current, path = frontier.popleft()
        edges = adjacency.get((trade_leg.transaction_hash, current, amount), ())
        if not edges:
            other_edges = [
                key
                for key in adjacency
                if key[0] == trade_leg.transaction_hash and key[1] == current
            ]
            if other_edges and current in protocol:
                raise InvariantError(
                    "Ambiguous split token path for "
                    f"{trade_leg.transaction_hash}:{trade_leg.log_index}"
                )
            if current not in protocol:
                endpoints.append((current, path))
            continue
        for destination, log in edges:
            if destination in visited:
                continue
            visited.add(destination)
            frontier.append((destination, [*path, log]))
    wallets = {wallet for wallet, _ in endpoints}
    if len(wallets) > 1 or len(endpoints) > 1:
        raise InvariantError(
            "Ambiguous multi-hop token path for "
            f"{trade_leg.transaction_hash}:{trade_leg.log_index}"
        )
    if endpoints:
        return endpoints[0]
    return ZERO, []
