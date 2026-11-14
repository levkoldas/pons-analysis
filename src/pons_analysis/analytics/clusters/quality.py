"""Cross-artifact quality metrics for evidence-connected wallet clusters.

Clusters identify wallet membership; execution, fee, and lifecycle artifacts
describe those wallets. This engine joins on wallet and reports cluster-level
volume-weighted execution impact, fee burden, deployed basis, ROI, entry-phase
composition, and fresh-wallet participation.
"""

import collections
import statistics
from typing import Any

from pons_analysis.analytics.market.trajectory import percentile
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore

QUALITY_FIELDS = (
    "cluster_id",
    "wallets",
    "execution_wallets",
    "execution_volume_eth",
    "execution_median_wallet_bps",
    "execution_weighted_bps",
    "fee_wallets",
    "fee_volume_eth",
    "quote_fee_eth",
    "tax_quote_eth",
    "total_fee_eth",
    "fee_burden_bps",
    "basis_deployed_eth",
    "net_quote_eth",
    "net_roi_bps",
    "roi_p25_bps",
    "roi_median_bps",
    "roi_p75_bps",
    "roi_min_bps",
    "roi_max_bps",
    "gas_eth",
    "profitable_wallets",
    "losing_wallets",
    "open_wallets",
    "closed_wallets",
    "curve_wallets",
    "v4_wallets",
    "transfer_wallets",
    "unknown_wallets",
    "fresh_wallets",
    "round_trips",
    "win_rate",
)


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _int(value: Any) -> int:
    return int(value) if value not in (None, "") else 0


def _map(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    mapped = {}
    for row in rows:
        wallet = row["wallet"].lower()
        if wallet in mapped:
            raise InvariantError(f"Duplicate wallet in {label}: {wallet}")
        mapped[wallet] = row
    return mapped


def _weighted(values: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    volume = sum(weight for _, weight in values)
    if not values:
        return None, None
    median = round(statistics.median(value for value, _ in values)) if values else None
    weighted = (
        round(sum(value * weight for value, weight in values) / volume)
        if volume
        else None
    )
    return median, weighted


def analyze_cluster_quality(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Join clustered wallets to execution, fee, and lifecycle artifacts."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    cluster_summary_path = "analysis/clusters/summary.json"
    cluster_rows_path = "analysis/clusters/clusters.csv"
    cluster_wallets_path = "analysis/clusters/wallets.csv"
    execution_summary_path = f"analysis/execution-{minutes}/summary.json"
    execution_wallets_path = f"analysis/execution-{minutes}/wallets.csv"
    fees_summary_path = f"analysis/fees-{minutes}/summary.json"
    fees_wallets_path = f"analysis/fees-{minutes}/wallets.csv"
    lifecycle_summary_path = f"analysis/lifecycle-{minutes}/summary.json"
    lifecycle_wallets_path = f"analysis/lifecycle-{minutes}/wallets.csv"
    for path, hint in (
        (cluster_summary_path, "analyze clusters"),
        (cluster_rows_path, "analyze clusters"),
        (cluster_wallets_path, "analyze clusters"),
        (execution_summary_path, f"analyze execution {minutes}"),
        (execution_wallets_path, f"analyze execution {minutes}"),
        (fees_summary_path, f"analyze fees {minutes}"),
        (fees_wallets_path, f"analyze fees {minutes}"),
        (lifecycle_summary_path, f"analyze lifecycle {minutes}"),
        (lifecycle_wallets_path, f"analyze lifecycle {minutes}"),
    ):
        if not store.exists(path):
            raise InvariantError(f"Missing cluster-quality evidence {path}; run {hint}")
    cluster_summary = store.read_json(cluster_summary_path) or {}
    execution_summary = store.read_json(execution_summary_path) or {}
    fees_summary = store.read_json(fees_summary_path) or {}
    lifecycle_summary = store.read_json(lifecycle_summary_path) or {}
    for label, summary in (
        ("Cluster", cluster_summary),
        ("Execution", execution_summary),
        ("Fee", fees_summary),
        ("Lifecycle", lifecycle_summary),
    ):
        if summary.get("minutes") not in (None, minutes):
            raise InvariantError(
                f"{label} artifacts have a different window; "
                f"re-run the corresponding analysis for {minutes}m"
            )

    cluster_base = {row["cluster_id"]: row for row in store.read_csv(cluster_rows_path)}
    if len(cluster_base) != cluster_summary.get("clusters"):
        raise InvariantError(
            "Cluster summary and clusters.csv disagree; re-run analyze clusters"
        )
    members: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in store.read_csv(cluster_wallets_path):
        cluster_id = row.get("cluster_id", "")
        if cluster_id:
            if cluster_id not in cluster_base:
                raise InvariantError(f"Unknown cluster id in wallets.csv: {cluster_id}")
            members[cluster_id].append(row)
    execution = _map(store.read_csv(execution_wallets_path), "execution wallets")
    fees = _map(store.read_csv(fees_wallets_path), "fee wallets")
    lifecycle = _map(store.read_csv(lifecycle_wallets_path), "lifecycle wallets")

    rows = []
    for cluster_id in sorted(cluster_base):
        base = cluster_base[cluster_id]
        cluster_members = members.get(cluster_id, [])
        wallet_count = _int(base.get("wallets"))
        if len(cluster_members) != wallet_count:
            raise InvariantError(
                f"Cluster {cluster_id} wallet count disagrees with membership"
            )
        execution_rows = [
            execution[member["wallet"].lower()]
            for member in cluster_members
            if member["wallet"].lower() in execution
        ]
        fee_rows = [
            fees[member["wallet"].lower()]
            for member in cluster_members
            if member["wallet"].lower() in fees
        ]
        lifecycle_rows = [
            lifecycle[member["wallet"].lower()]
            for member in cluster_members
            if member["wallet"].lower() in lifecycle
        ]
        execution_pairs = [
            (float(row["volume_weighted_abs_bps"]), float(row["volume_eth"]))
            for row in execution_rows
            if row.get("volume_weighted_abs_bps") not in (None, "")
        ]
        execution_median, execution_weighted = _weighted(execution_pairs)
        execution_volume = sum(
            float(row.get("volume_eth") or 0) for row in execution_rows
        )
        fee_volume = sum(float(row.get("volume_eth") or 0) for row in fee_rows)
        total_fee = sum(float(row.get("total_fee_eth") or 0) for row in fee_rows)
        quote_fee = sum(float(row.get("fee_quote_eth") or 0) for row in fee_rows)
        tax_quote = sum(float(row.get("tax_quote_eth") or 0) for row in fee_rows)
        basis = sum(float(row.get("basis_deployed_eth") or 0) for row in lifecycle_rows)
        net_values = [
            (
                None
                if row.get("net_quote_eth") in (None, "")
                else float(row["net_quote_eth"])
            )
            for row in lifecycle_rows
        ]
        net_known = all(value is not None for value in net_values)
        net = (
            sum(value for value in net_values if value is not None)
            if net_known
            else None
        )
        phase_counts = collections.Counter(
            row.get("entry_phase", "unknown") for row in lifecycle_rows
        )
        open_wallets = sum(row.get("status") == "open" for row in lifecycle_rows)
        roi_values = [
            int(row["net_roi_bps"])
            for row in lifecycle_rows
            if row.get("net_roi_bps") not in (None, "")
        ]
        gas = sum(float(row.get("gas_quote_eth") or 0) for row in lifecycle_rows)
        sale_pnl = sum(float(row.get("sale_pnl_eth") or 0) for row in lifecycle_rows)
        roi_unrealized = [
            (
                None
                if row.get("unrealized_quote_eth") in (None, "")
                else float(row["unrealized_quote_eth"])
            )
            for row in lifecycle_rows
        ]
        roi_unrealized_known = all(value is not None for value in roi_unrealized)
        roi_unrealized_total = (
            sum(value for value in roi_unrealized if value is not None)
            if roi_unrealized_known
            else None
        )
        roi_net = (
            sale_pnl + roi_unrealized_total - gas
            if roi_unrealized_total is not None
            else None
        )
        rows.append(
            {
                "cluster_id": cluster_id,
                "wallets": wallet_count,
                "execution_wallets": len(execution_rows),
                "execution_volume_eth": execution_volume,
                "execution_median_wallet_bps": execution_median,
                "execution_weighted_bps": execution_weighted,
                "fee_wallets": len(fee_rows),
                "fee_volume_eth": fee_volume,
                "quote_fee_eth": quote_fee,
                "tax_quote_eth": tax_quote,
                "total_fee_eth": total_fee,
                "fee_burden_bps": (
                    round(total_fee * 10_000 / fee_volume) if fee_volume else None
                ),
                "basis_deployed_eth": basis,
                "net_quote_eth": net,
                "net_roi_bps": (
                    round(roi_net * 10_000 / basis)
                    if roi_net is not None and basis
                    else None
                ),
                "roi_p25_bps": percentile(roi_values, 25),
                "roi_median_bps": (
                    round(statistics.median(roi_values)) if roi_values else None
                ),
                "roi_p75_bps": percentile(roi_values, 75),
                "roi_min_bps": min(roi_values) if roi_values else None,
                "roi_max_bps": max(roi_values) if roi_values else None,
                "gas_eth": gas,
                "profitable_wallets": (
                    sum(value > 0 for value in net_values if value is not None)
                    if net_known
                    else None
                ),
                "losing_wallets": (
                    sum(value < 0 for value in net_values if value is not None)
                    if net_known
                    else None
                ),
                "open_wallets": open_wallets,
                "closed_wallets": len(lifecycle_rows) - open_wallets,
                "curve_wallets": phase_counts.get("curve", 0),
                "v4_wallets": phase_counts.get("v4", 0),
                "transfer_wallets": phase_counts.get("transfer", 0),
                "unknown_wallets": phase_counts.get("unknown", 0),
                "fresh_wallets": sum(
                    str(member.get("fresh", "")).lower() == "true"
                    for member in cluster_members
                ),
                "round_trips": _int(base.get("round_trips")),
                "win_rate": _float(base.get("win_rate")),
            }
        )

    total_execution_volume = sum(row["execution_volume_eth"] for row in rows)
    total_fee_volume = sum(row["fee_volume_eth"] for row in rows)
    total_fees = sum(row["total_fee_eth"] for row in rows)
    execution_pairs = [
        (row["execution_weighted_bps"], row["execution_volume_eth"])
        for row in rows
        if row["execution_weighted_bps"] is not None
    ]
    execution_median, execution_weighted = _weighted(execution_pairs)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "scope": (
            "evidence-connected clusters joined to wallet-level execution, fee, "
            "and lifecycle artifacts; singleton wallets are excluded"
        ),
        "clusters": len(rows),
        "wallets": sum(row["wallets"] for row in rows),
        "execution_wallets": sum(row["execution_wallets"] for row in rows),
        "execution_volume_eth": total_execution_volume,
        "execution_median_cluster_bps": execution_median,
        "execution_weighted_bps": execution_weighted,
        "fee_wallets": sum(row["fee_wallets"] for row in rows),
        "fee_volume_eth": total_fee_volume,
        "total_fee_eth": total_fees,
        "fee_burden_bps": (
            round(total_fees * 10_000 / total_fee_volume) if total_fee_volume else None
        ),
        "gas_eth": sum(row["gas_eth"] for row in rows),
        "profitable_wallets": (
            sum(row["profitable_wallets"] for row in rows)
            if all(row["profitable_wallets"] is not None for row in rows)
            else None
        ),
        "losing_wallets": (
            sum(row["losing_wallets"] for row in rows)
            if all(row["losing_wallets"] is not None for row in rows)
            else None
        ),
        "rows": rows,
        "top_by_execution": sorted(
            (row for row in rows if row["execution_weighted_bps"] is not None),
            key=lambda row: (
                -row["execution_weighted_bps"],
                -row["execution_volume_eth"],
                row["cluster_id"],
            ),
        )[:10],
        "top_by_fees": sorted(
            (row for row in rows if row["fee_burden_bps"] is not None),
            key=lambda row: (-row["fee_burden_bps"], row["cluster_id"]),
        )[:10],
        "top_by_roi": sorted(
            (row for row in rows if row["roi_median_bps"] is not None),
            key=lambda row: (-row["roi_median_bps"], row["cluster_id"]),
        )[:10],
    }
    out = output or f"analysis/cluster-quality-{minutes}"
    store.write_csv(f"{out}/clusters.csv", rows, fields=QUALITY_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
