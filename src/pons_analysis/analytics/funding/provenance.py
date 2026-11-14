"""Funding provenance relative to each wallet's first observed trade.

Funding edges answer where native value came from; the position ledger answers
when a wallet first traded. This engine joins them and reports whether wallets
were prefunded before their first trade, the native funding source, and the
lead time. Native funding is evidence, not proof of common ownership.
"""

import collections
import datetime
from typing import Any

from pons_analysis.analytics.positions import median_int
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _timestamp(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return int(parsed.timestamp())


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


WALLET_FIELDS = (
    "wallet",
    "cluster_id",
    "fresh",
    "entry_phase",
    "first_trade_timestamp",
    "first_inflow_timestamp",
    "first_inflow_block",
    "first_inflow_source",
    "first_inflow_value_eth",
    "first_inflow_external",
    "lead_seconds",
    "prefunded",
    "tokens_end",
    "net_quote_eth",
    "trade_count",
)


def analyze_provenance(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Join native funding inflows to first-trade timing and wallet metadata."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    edges_path = "analysis/funding/edges.csv"
    funding_wallets_path = "analysis/funding/wallets.csv"
    positions_path = f"analysis/positions-{minutes}/positions.csv"
    for path, hint in (
        (edges_path, "analyze funding"),
        (funding_wallets_path, "analyze funding"),
        (positions_path, f"analyze positions {minutes}"),
    ):
        if not store.exists(path):
            raise InvariantError(f"Missing provenance evidence {path}; run {hint}")
    edges = store.read_csv(edges_path)
    funding_rows = store.read_csv(funding_wallets_path)
    position_rows = store.read_csv(positions_path)
    if not edges:
        raise InvariantError("Funding evidence contains no edges")
    funding = {row["wallet"].lower(): row for row in funding_rows}
    positions = {row["wallet"].lower(): row for row in position_rows}
    clusters: dict[str, str] = {}
    if store.exists("analysis/clusters/wallets.csv"):
        clusters = {
            row["wallet"].lower(): row.get("cluster_id", "")
            for row in store.read_csv("analysis/clusters/wallets.csv")
            if row.get("cluster_id")
        }
    core = set(funding)
    protocol = {
        address.lower()
        for address in (
            profile.manager,
            profile.router,
            profile.hook,
            profile.curve,
            profile.factory,
            profile.token,
            *profile.protocol_sweepers,
        )
        if address
    }
    inbound: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for edge in edges:
        destination = edge["destination"].lower()
        if destination not in core or edge["source"].lower() == destination:
            continue
        timestamp = _timestamp(edge.get("timestamp"))
        if timestamp is None:
            continue
        inbound[destination].append(
            {
                "timestamp": timestamp,
                "block": edge.get("block"),
                "source": edge["source"].lower(),
                "value_eth": _float(edge.get("value_eth")) or 0.0,
                "protocol": edge["source"].lower() in protocol,
                "external": (
                    edge["source"].lower() not in core
                    and edge["source"].lower() not in protocol
                ),
            }
        )
    for rows in inbound.values():
        rows.sort(key=lambda row: (row["timestamp"], str(row["block"]), row["source"]))
    rows = []
    for wallet in sorted(set(funding) & set(positions)):
        position = positions[wallet]
        meta = funding[wallet]
        first_trade_seconds = _float(position.get("first_trade_seconds"))
        first_trade = (
            profile.start_timestamp + int(first_trade_seconds)
            if first_trade_seconds is not None
            else None
        )
        inflows = [row for row in inbound.get(wallet, []) if not row["protocol"]]
        external = [row for row in inflows if row["external"]]
        first = external[0] if external else (inflows[0] if inflows else None)
        lead = (
            first_trade - first["timestamp"]
            if first and first_trade is not None
            else None
        )
        rows.append(
            {
                "wallet": wallet,
                "cluster_id": clusters.get(wallet, ""),
                "fresh": str(meta.get("fresh", "")).lower() == "true",
                "entry_phase": position.get("entry_phase", ""),
                "first_trade_timestamp": first_trade,
                "first_inflow_timestamp": first["timestamp"] if first else None,
                "first_inflow_block": first["block"] if first else None,
                "first_inflow_source": first["source"] if first else "",
                "first_inflow_value_eth": first["value_eth"] if first else None,
                "first_inflow_external": first["external"] if first else None,
                "lead_seconds": lead,
                "prefunded": lead >= 0 if lead is not None else None,
                "tokens_end": _float(position.get("tokens_end")) or 0.0,
                "net_quote_eth": _float(position.get("net_quote_eth")),
                "trade_count": int(position.get("trade_count") or 0),
            }
        )
    rows.sort(
        key=lambda row: (
            row["prefunded"] is not True,
            -(row["lead_seconds"] if row["lead_seconds"] is not None else -(10**18)),
            row["wallet"],
        )
    )
    prefunded = [row for row in rows if row["prefunded"] is True]
    postfunded = [row for row in rows if row["prefunded"] is False]
    unknown = [row for row in rows if row["prefunded"] is None]
    leads = [
        row["lead_seconds"] for row in prefunded if row["lead_seconds"] is not None
    ]
    sources: dict[str, dict[str, Any]] = {}
    for row in prefunded:
        source = row["first_inflow_source"]
        if not source or not row["first_inflow_external"]:
            continue
        data = sources.setdefault(source, {"wallets": 0, "value_eth": 0.0})
        data["wallets"] += 1
        data["value_eth"] += row["first_inflow_value_eth"] or 0.0
    phase_groups = collections.defaultdict(list)
    for row in rows:
        phase_groups[row["entry_phase"] or "unknown"].append(row)
    by_phase = []
    for phase in sorted(phase_groups):
        selected = phase_groups[phase]
        selected_leads = [
            row["lead_seconds"]
            for row in selected
            if row["prefunded"] is True and row["lead_seconds"] is not None
        ]
        by_phase.append(
            {
                "entry_phase": phase,
                "wallets": len(selected),
                "prefunded_wallets": sum(row["prefunded"] is True for row in selected),
                "median_lead_seconds": median_int(selected_leads),
            }
        )
    fresh_rows = [row for row in rows if row["fresh"]]
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "scope": (
            "first external native inflow relative to first observed trade; "
            "native funding is evidence, not proof of common ownership"
        ),
        "wallets": len(rows),
        "prefunded_wallets": len(prefunded),
        "postfunded_wallets": len(postfunded),
        "unknown_timing": len(unknown),
        "prefunded_bps": (round(len(prefunded) * 10_000 / len(rows)) if rows else None),
        "median_prefund_lead_seconds": median_int(leads),
        "max_prefund_lead_seconds": max(leads) if leads else None,
        "total_prefund_value_eth": sum(
            row["first_inflow_value_eth"] or 0.0 for row in prefunded
        ),
        "fresh_wallets": len(fresh_rows),
        "fresh_prefunded": sum(row["prefunded"] is True for row in fresh_rows),
        "by_entry_phase": by_phase,
        "top_sources": sorted(
            (
                {
                    "source": source,
                    "wallets": data["wallets"],
                    "value_eth": data["value_eth"],
                }
                for source, data in sources.items()
            ),
            key=lambda row: (-row["wallets"], -row["value_eth"], row["source"]),
        )[:10],
        "rows": rows,
    }
    out = output or f"analysis/provenance-{minutes}"
    store.write_csv(f"{out}/wallets.csv", rows, fields=WALLET_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
