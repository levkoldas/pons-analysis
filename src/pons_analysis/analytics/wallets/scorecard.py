"""Unified per-wallet scorecard across position, fee, execution, flow, and funding artifacts.

This is a read-only join over already-derived wallet tables. Missing optional
artifacts leave their fields empty; the position ledger is required. No score is
synthesized: callers rank wallets by explicit metrics such as net PnL, ROI,
execution impact, or fees.
"""

from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _int(value: Any) -> int:
    return int(value) if value not in (None, "") else 0


def _optional_bool(value: Any) -> bool | None:
    text = str(value).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["wallet"].lower(): row for row in rows}


WALLET_FIELDS = (
    "wallet",
    "cluster_id",
    "entry_phase",
    "entry_route",
    "entry_selector",
    "status",
    "tokens_end",
    "realized_quote_eth",
    "unrealized_quote_eth",
    "gas_quote_eth",
    "net_quote_eth",
    "basis_deployed_eth",
    "net_roi_bps",
    "token_retention_bps",
    "fee_volume_eth",
    "total_fee_eth",
    "fee_burden_bps",
    "execution_volume_eth",
    "execution_weighted_bps",
    "execution_max_bps",
    "flow_net_eth",
    "flow_gross_eth",
    "holding_seconds",
    "trade_count",
    "fresh",
    "prefunded",
    "funding_lead_seconds",
)


def analyze_wallets(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Join per-wallet artifacts into one scorecard table."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    positions_path = f"analysis/positions-{minutes}/positions.csv"
    if not store.exists(positions_path):
        raise InvariantError(
            f"Missing wallet evidence {positions_path}; run analyze positions {minutes}"
        )
    positions = store.read_csv(positions_path)
    if not positions:
        raise InvariantError(f"Position analysis produced no wallets for {minutes}m")
    positions_summary = (
        store.read_json(f"analysis/positions-{minutes}/summary.json") or {}
    )
    position_performance = positions_summary.get("performance") or {}
    optional = {
        "fees": f"analysis/fees-{minutes}/wallets.csv",
        "execution": f"analysis/execution-{minutes}/wallets.csv",
        "lifecycle": f"analysis/lifecycle-{minutes}/wallets.csv",
        "flow": f"analysis/flow-{minutes}/wallets.csv",
        "provenance": f"analysis/provenance-{minutes}/wallets.csv",
        "funding": "analysis/funding/wallets.csv",
        "clusters": "analysis/clusters/wallets.csv",
        "route-performance": f"analysis/route-performance-{minutes}/wallets.csv",
        "retention": f"analysis/retention-{minutes}/wallets.csv",
    }
    tables = {
        name: _map(store.read_csv(path)) if store.exists(path) else {}
        for name, path in optional.items()
    }
    rows = []
    for row in positions:
        wallet = row["wallet"].lower()
        fee = tables["fees"].get(wallet, {})
        execution = tables["execution"].get(wallet, {})
        lifecycle = tables["lifecycle"].get(wallet, {})
        flow = tables["flow"].get(wallet, {})
        provenance = tables["provenance"].get(wallet, {})
        funding = tables["funding"].get(wallet, {})
        cluster = tables["clusters"].get(wallet, {})
        route = tables["route-performance"].get(wallet, {})
        retention = tables["retention"].get(wallet, {})
        rows.append(
            {
                "wallet": wallet,
                "cluster_id": cluster.get("cluster_id", ""),
                "entry_phase": row.get("entry_phase", ""),
                "entry_route": route.get("route", ""),
                "entry_selector": route.get("selector", ""),
                "status": lifecycle.get("status", ""),
                "tokens_end": _float(row.get("tokens_end")),
                "realized_quote_eth": _float(row.get("realized_quote_eth")),
                "unrealized_quote_eth": _float(row.get("unrealized_quote_eth")),
                "gas_quote_eth": _float(row.get("gas_quote_eth")),
                "net_quote_eth": _float(row.get("net_quote_eth")),
                "basis_deployed_eth": _float(lifecycle.get("basis_deployed_eth")),
                "net_roi_bps": _float(lifecycle.get("net_roi_bps")),
                "token_retention_bps": _float(retention.get("token_retention_bps")),
                "fee_volume_eth": _float(fee.get("volume_eth")),
                "total_fee_eth": _float(fee.get("total_fee_eth")),
                "fee_burden_bps": _float(fee.get("fee_burden_bps")),
                "execution_volume_eth": _float(execution.get("volume_eth")),
                "execution_weighted_bps": _float(
                    execution.get("volume_weighted_abs_bps")
                ),
                "execution_max_bps": _float(execution.get("max_abs_bps")),
                "flow_net_eth": _float(flow.get("net_flow_eth")),
                "flow_gross_eth": _float(flow.get("gross_volume_eth")),
                "holding_seconds": _float(row.get("holding_seconds")),
                "trade_count": _int(row.get("trade_count")),
                "fresh": str(funding.get("fresh", "")).lower() == "true",
                "prefunded": (
                    _optional_bool(provenance.get("prefunded")) if provenance else None
                ),
                "funding_lead_seconds": _float(provenance.get("lead_seconds")),
            }
        )
    net = [row["net_quote_eth"] for row in rows]
    net_known = all(value is not None for value in net)
    known_net = [value for value in net if value is not None]
    basis = sum(row["basis_deployed_eth"] or 0.0 for row in rows)
    total_net = sum(known_net) if net_known else None
    fee_rows = [row for row in rows if row["total_fee_eth"] is not None]
    execution_rows = [row for row in rows if row["execution_weighted_bps"] is not None]
    fee_volume = sum(row["fee_volume_eth"] or 0.0 for row in fee_rows)
    total_fees = sum(row["total_fee_eth"] or 0.0 for row in fee_rows)
    execution_volume = sum(row["execution_volume_eth"] or 0.0 for row in execution_rows)
    execution_weighted = (
        round(
            sum(
                (row["execution_weighted_bps"] or 0.0)
                * (row["execution_volume_eth"] or 0.0)
                for row in execution_rows
            )
            / execution_volume
        )
        if execution_volume
        else None
    )
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "wallets": len(rows),
        "profitable_wallets": (
            sum(value > 0 for value in known_net) if net_known else None
        ),
        "losing_wallets": (
            sum(value < 0 for value in known_net) if net_known else None
        ),
        "flat_wallets": (sum(value == 0 for value in known_net) if net_known else None),
        "net_quote_eth": total_net,
        "basis_deployed_eth": position_performance.get("capital_deployed_eth", basis),
        "roi_net_eth": position_performance.get("net_roi_eth"),
        "net_roi_bps": position_performance.get(
            "net_roi_bps",
            round(total_net * 10_000 / basis)
            if total_net is not None and basis
            else None,
        ),
        "fee_wallets": len(fee_rows),
        "fee_volume_eth": fee_volume,
        "total_fee_eth": total_fees,
        "fee_burden_bps": (
            round(total_fees * 10_000 / fee_volume) if fee_volume else None
        ),
        "execution_wallets": len(execution_rows),
        "execution_volume_eth": execution_volume,
        "execution_weighted_bps": execution_weighted,
        "prefunded_wallets": sum(row["prefunded"] is True for row in rows),
        "fresh_wallets": sum(row["fresh"] for row in rows),
        "route_wallets": sum(bool(row["entry_route"]) for row in rows),
        "retention_wallets": sum(
            row["token_retention_bps"] is not None for row in rows
        ),
        "top_by_net": sorted(
            rows, key=lambda row: (-(row["net_quote_eth"] or 0.0), row["wallet"])
        )[:20],
        "top_by_roi": sorted(
            (row for row in rows if row["net_roi_bps"] is not None),
            key=lambda row: (-row["net_roi_bps"], row["wallet"]),
        )[:20],
        "top_by_impact": sorted(
            execution_rows,
            key=lambda row: (-row["execution_weighted_bps"], row["wallet"]),
        )[:20],
        "top_by_fees": sorted(
            fee_rows,
            key=lambda row: (-(row["total_fee_eth"] or 0.0), row["wallet"]),
        )[:20],
        "top_by_retention": sorted(
            (row for row in rows if row["token_retention_bps"] is not None),
            key=lambda row: (
                -row["token_retention_bps"],
                -(row["net_quote_eth"] or 0.0),
                row["wallet"],
            ),
        )[:20],
    }
    out = output or f"analysis/wallets-{minutes}"
    store.write_csv(f"{out}/wallets.csv", rows, fields=WALLET_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
