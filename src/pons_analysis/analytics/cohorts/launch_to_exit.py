"""Launch-to-exit cohort graph over rotations and direct transfers.

The engine re-runs the window with the requested cohort roots so the window's
rotation and direct-transfer edges are seeded correctly, re-runs the position
ledger for exact wallet PnL, then walks the edge graph breadth-first. The
result is a generation table, terminal holders, and cohort/descendant PnL and
unrealized-value aggregates. Amounts stay integer until presentation fields.
"""

import collections
from collections.abc import Iterable
from typing import Any

from pons_analysis.analytics import positions as positions_analysis
from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.analytics.market import window as window_analysis
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _edges(
    routes: Iterable[dict[str, Any]], direct: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    edges = []
    for route in routes:
        edges.append(
            {
                "source": addr(route["source_wallet"]),
                "destination": addr(route["destination_wallet"]),
                "timestamp": int(route["timestamp"]),
                "block": int(route["block"]),
                "tx_hash": route["tx_hash"],
                "kind": "rotation",
                "tokens_raw": int(route["input_tokens_raw"]),
            }
        )
    for row in direct:
        edges.append(
            {
                "source": addr(row["source"]),
                "destination": addr(row["destination"]),
                "timestamp": int(row["timestamp"]),
                "block": int(row.get("block") or 0),
                "tx_hash": row["tx_hash"],
                "kind": "transfer",
                "tokens_raw": int(row["tokens_raw"]),
            }
        )
    edges.sort(
        key=lambda edge: (
            edge["timestamp"],
            edge["block"],
            edge["tx_hash"],
            edge["source"],
            edge["destination"],
            edge["kind"],
        )
    )
    return edges


def _graph(
    roots: tuple[str, ...],
    edges: list[dict[str, Any]],
    start: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    meta = {
        root: {
            "generation": 0,
            "parent": "",
            "relation": "cohort",
            "first_seen_seconds": 0,
        }
        for root in roots
    }
    outgoing: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for edge in edges:
        outgoing[edge["source"]].append(edge)
    for source in outgoing:
        outgoing[source].sort(
            key=lambda edge: (
                edge["timestamp"],
                edge["block"],
                edge["tx_hash"],
                edge["destination"],
            )
        )
    queue = collections.deque(roots)
    while queue:
        source = queue.popleft()
        for edge in outgoing.get(source, ()):
            destination = edge["destination"]
            if destination in meta:
                continue
            parent = meta[source]
            meta[destination] = {
                "generation": parent["generation"] + 1,
                "parent": source,
                "relation": edge["kind"],
                "first_seen_seconds": edge["timestamp"] - start,
            }
            queue.append(destination)
    linked_edges = sum(1 for edge in edges if edge["source"] in meta)
    return meta, {
        "rotations": sum(edge["kind"] == "rotation" for edge in edges),
        "transfers": sum(edge["kind"] == "transfer" for edge in edges),
        "linked": linked_edges,
        "used": len(meta) - len(roots),
    }


def _wallet_rows(
    meta: dict[str, dict[str, Any]],
    positions: dict[str, dict[str, Any]],
    profile: Launch,
) -> list[dict[str, Any]]:
    rows = []
    for wallet, info in meta.items():
        position = positions.get(wallet)
        if position is None:
            raise InvariantError(
                f"Linked cohort wallet {wallet} has no position evidence"
            )
        tokens_end_raw = position["tokens_end_raw"]
        realized = position["realized_raw"]
        unrealized = position["unrealized_raw"]
        gas = position["gas_raw"]
        net = position["net_raw"]
        rows.append(
            {
                "wallet": wallet,
                "generation": info["generation"],
                "parent": info["parent"],
                "relation": info["relation"],
                "first_seen_seconds": info["first_seen_seconds"],
                "terminal": tokens_end_raw > 0,
                "tokens_end_raw": tokens_end_raw,
                "tokens_end": from_wei(tokens_end_raw, profile.decimals),
                "realized_quote_raw": realized,
                "realized_quote_eth": _eth(realized),
                "unrealized_quote_raw": unrealized,
                "unrealized_quote_eth": _eth(unrealized),
                "gas_quote_raw": gas,
                "gas_quote_eth": _eth(gas),
                "net_quote_raw": net,
                "net_quote_eth": _eth(net),
                "last_trade_seconds": position["last_trade_seconds"],
                "cost_basis_remaining_raw": position["cost_basis_raw"],
                "tokens_out_raw": position["tokens_out_raw"],
                "trade_count": position["trade_count"],
            }
        )
    rows.sort(
        key=lambda row: (
            row["generation"],
            row["first_seen_seconds"],
            row["wallet"],
        )
    )
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def optional_sum(key: str) -> int | None:
        if not rows:
            return 0
        values = [row[key] for row in rows]
        if any(value is None for value in values):
            return None
        return sum(values)

    terminal_rows = [row for row in rows if row["terminal"]]
    terminal_values = [
        (
            row["unrealized_quote_raw"] + row["cost_basis_remaining_raw"]
            if row["unrealized_quote_raw"] is not None
            else None
        )
        for row in terminal_rows
    ]
    terminal_value = (
        sum(terminal_values)
        if all(value is not None for value in terminal_values)
        else None
    )
    return {
        "wallets": len(rows),
        "terminal_holders": len(terminal_rows),
        "terminal_tokens_raw": sum(row["tokens_end_raw"] for row in terminal_rows),
        "terminal_tokens": sum(row["tokens_end"] for row in terminal_rows),
        "terminal_value_raw": terminal_value,
        "terminal_value_eth": _eth(terminal_value),
        "tokens_end_raw": sum(row["tokens_end_raw"] for row in rows),
        "tokens_end": sum(row["tokens_end"] for row in rows),
        "realized_quote_raw": sum(row["realized_quote_raw"] for row in rows),
        "realized_quote_eth": _eth(sum(row["realized_quote_raw"] for row in rows)),
        "unrealized_quote_raw": optional_sum("unrealized_quote_raw"),
        "unrealized_quote_eth": _eth(optional_sum("unrealized_quote_raw")),
        "gas_quote_raw": sum(row["gas_quote_raw"] for row in rows),
        "gas_quote_eth": _eth(sum(row["gas_quote_raw"] for row in rows)),
        "net_quote_raw": optional_sum("net_quote_raw"),
        "net_quote_eth": _eth(optional_sum("net_quote_raw")),
    }


def analyze_cohort(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    cohort: Iterable[str],
    output: str | None = None,
) -> dict[str, Any]:
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    roots = tuple(sorted({addr(item) for item in cohort}))
    if not roots:
        raise ValueError("Cohort analysis requires at least one wallet")
    out = output or f"analysis/cohort-{minutes}"

    window = window_analysis.analyze_window(
        store,
        profile,
        minutes=minutes,
        cohort=roots,
        return_details=True,
    )
    positions_summary = positions_analysis.analyze_positions(
        store, profile, minutes=minutes, cohort=roots
    )
    positions = positions_analysis.read_positions(store, minutes)
    edges = _edges(window.routes, window.direct)
    meta, edge_counts = _graph(roots, edges, profile.start_timestamp)
    rows = _wallet_rows(meta, positions, profile)
    terminal_rows = sorted(
        (row for row in rows if row["terminal"]),
        key=lambda row: (-row["tokens_end_raw"], row["wallet"]),
    )
    terminal_tokens = sum(row["tokens_end_raw"] for row in terminal_rows)
    linked_tokens = sum(row["tokens_end_raw"] for row in rows)
    if terminal_tokens != linked_tokens:
        raise InvariantError(
            "Cohort terminal tokens do not match linked balances: "
            f"{terminal_tokens} != {linked_tokens}"
        )
    root_rows = [row for row in rows if row["generation"] == 0]
    descendant_rows = [row for row in rows if row["generation"] > 0]
    generations = sorted({row["generation"] for row in rows})
    generation_rows = []
    for generation in generations:
        group = [row for row in rows if row["generation"] == generation]
        aggregate = _aggregate(group)
        aggregate["generation"] = generation
        generation_rows.append(aggregate)
    terminal_value = (
        sum(
            row["unrealized_quote_raw"] + row["cost_basis_remaining_raw"]
            for row in terminal_rows
        )
        if all(row["unrealized_quote_raw"] is not None for row in terminal_rows)
        else None
    )
    concentration_bps = (
        terminal_rows[0]["tokens_end_raw"] * 10_000 // terminal_tokens
        if terminal_rows and terminal_tokens
        else 0
    )
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "start_timestamp": profile.start_timestamp,
        "end_timestamp_exclusive": profile.start_timestamp + minutes * 60,
        "start_utc": utc(profile.start_timestamp),
        "end_utc": utc(profile.start_timestamp + minutes * 60),
        "cohort_wallets": len(roots),
        "linked_wallets": len(rows),
        "additional_wallets": len(rows) - len(roots),
        "exited_wallets": len(rows) - len(terminal_rows),
        "generations": max(generations) if generations else 0,
        "generation_counts": {
            str(generation): sum(row["generation"] == generation for row in rows)
            for generation in generations
        },
        "edges": {"total": len(edges), **edge_counts},
        "terminal_holders": len(terminal_rows),
        "terminal_tokens_raw": terminal_tokens,
        "terminal_tokens": from_wei(terminal_tokens, profile.decimals),
        "terminal_value_raw": terminal_value,
        "terminal_value_eth": _eth(terminal_value),
        "linked_tokens_end_raw": linked_tokens,
        "linked_tokens_end": from_wei(linked_tokens, profile.decimals),
        "reconciled": terminal_tokens == linked_tokens,
        "terminal_concentration_bps": concentration_bps,
        "realized_quote_raw": sum(row["realized_quote_raw"] for row in rows),
        "unrealized_quote_raw": (
            sum(row["unrealized_quote_raw"] for row in rows)
            if all(row["unrealized_quote_raw"] is not None for row in rows)
            else None
        ),
        "gas_quote_raw": sum(row["gas_quote_raw"] for row in rows),
        "net_quote_raw": (
            sum(row["net_quote_raw"] for row in rows)
            if all(row["net_quote_raw"] is not None for row in rows)
            else None
        ),
        "roots": _aggregate(root_rows),
        "descendants": _aggregate(descendant_rows),
        "generation_rows": generation_rows,
        "top_terminal_holders": terminal_rows[:20],
        "mark": positions_summary.get("mark"),
    }
    summary["realized_quote_eth"] = _eth(summary["realized_quote_raw"])
    summary["unrealized_quote_eth"] = _eth(summary["unrealized_quote_raw"])
    summary["gas_quote_eth"] = _eth(summary["gas_quote_raw"])
    summary["net_quote_eth"] = _eth(summary["net_quote_raw"])
    store.write_csv(
        f"{out}/generations.csv",
        rows,
        fields=(
            "wallet",
            "generation",
            "parent",
            "relation",
            "first_seen_seconds",
            "terminal",
            "tokens_end_raw",
            "tokens_end",
            "realized_quote_raw",
            "realized_quote_eth",
            "unrealized_quote_raw",
            "unrealized_quote_eth",
            "gas_quote_raw",
            "gas_quote_eth",
            "net_quote_raw",
            "net_quote_eth",
            "last_trade_seconds",
            "cost_basis_remaining_raw",
            "tokens_out_raw",
            "trade_count",
        ),
    )
    store.write_csv(
        f"{out}/terminal_holders.csv",
        [
            {
                **row,
                "pct_supply": row["tokens_end_raw"] * 100 / profile.supply,
            }
            for row in terminal_rows
        ],
        fields=(
            "wallet",
            "generation",
            "parent",
            "relation",
            "tokens_end_raw",
            "tokens_end",
            "pct_supply",
            "unrealized_quote_raw",
            "unrealized_quote_eth",
            "net_quote_raw",
            "net_quote_eth",
        ),
    )
    store.write_json(f"{out}/summary.json", summary)
    return summary
