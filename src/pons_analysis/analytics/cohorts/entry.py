"""Entry-time cohort performance from the position ledger.

Wallets are grouped by the UTC bucket of their first observed token activity.
Each cohort reports size, open/closed status, tokens in/end, exact FIFO basis,
sale PnL, unrealized/gas/net, aggregate and median ROI, holding span, and entry
phase composition. Gas-only wallets without token activity are counted as
unbucketable rather than assigned a fake entry time.
"""

from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.analytics.positions import median_int
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _int(value: Any) -> int:
    return int(value) if value not in (None, "") else 0


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "") else None


COHORT_FIELDS = (
    "bucket",
    "start_timestamp",
    "start_utc",
    "wallets",
    "open_wallets",
    "closed_wallets",
    "tokens_in_raw",
    "tokens_in",
    "tokens_end_raw",
    "tokens_end",
    "basis_deployed_raw",
    "basis_deployed_eth",
    "realized_quote_raw",
    "realized_quote_eth",
    "sale_pnl_raw",
    "sale_pnl_eth",
    "unrealized_quote_raw",
    "unrealized_quote_eth",
    "gas_quote_raw",
    "gas_quote_eth",
    "net_quote_raw",
    "net_quote_eth",
    "roi_net_raw",
    "roi_net_eth",
    "roi_bps",
    "median_wallet_roi_bps",
    "median_holding_seconds",
    "curve_wallets",
    "v4_wallets",
    "transfer_wallets",
    "unknown_wallets",
    "before_launch",
)

WALLET_FIELDS = (
    "wallet",
    "entry_bucket",
    "entry_utc",
    "entry_phase",
    "open",
    "tokens_end_raw",
    "tokens_end",
    "basis_deployed_raw",
    "basis_deployed_eth",
    "realized_quote_raw",
    "realized_quote_eth",
    "sale_pnl_raw",
    "sale_pnl_eth",
    "unrealized_quote_raw",
    "unrealized_quote_eth",
    "gas_quote_raw",
    "gas_quote_eth",
    "net_quote_raw",
    "net_quote_eth",
    "roi_bps",
    "holding_seconds",
)


def _aggregate(rows: list[dict[str, Any]], profile: Launch) -> dict[str, Any]:
    basis = sum(row["basis_deployed_raw"] for row in rows)
    realized = sum(row["realized_quote_raw"] for row in rows)
    sale_pnl = sum(row["sale_pnl_raw"] for row in rows)
    gas = sum(row["gas_quote_raw"] for row in rows)
    unrealized = (
        sum(row["unrealized_quote_raw"] for row in rows)
        if all(row["unrealized_quote_raw"] is not None for row in rows)
        else None
    )
    roi_net = sale_pnl + unrealized - gas if unrealized is not None else None
    net = (
        sum(row["net_quote_raw"] for row in rows)
        if all(row["net_quote_raw"] is not None for row in rows)
        else None
    )
    rois = [row["roi_bps"] for row in rows if row["roi_bps"] is not None]
    holds = [
        row["holding_seconds"] for row in rows if row["holding_seconds"] is not None
    ]
    tokens_in = sum(row["tokens_in_raw"] for row in rows)
    tokens_end = sum(row["tokens_end_raw"] for row in rows)
    phases = {
        phase: sum(row["entry_phase"] == phase for row in rows)
        for phase in (
            "curve",
            "v4",
            "transfer",
            "unknown",
        )
    }
    return {
        "wallets": len(rows),
        "open_wallets": sum(row["open"] for row in rows),
        "closed_wallets": sum(not row["open"] for row in rows),
        "tokens_in_raw": tokens_in,
        "tokens_in": from_wei(tokens_in, profile.decimals),
        "tokens_end_raw": tokens_end,
        "tokens_end": from_wei(tokens_end, profile.decimals),
        "basis_deployed_raw": basis,
        "basis_deployed_eth": from_wei(basis),
        "realized_quote_raw": realized,
        "realized_quote_eth": from_wei(realized),
        "sale_pnl_raw": sale_pnl,
        "sale_pnl_eth": from_wei(sale_pnl),
        "unrealized_quote_raw": unrealized,
        "unrealized_quote_eth": from_wei(unrealized)
        if unrealized is not None
        else None,
        "gas_quote_raw": gas,
        "gas_quote_eth": from_wei(gas),
        "net_quote_raw": net,
        "net_quote_eth": from_wei(net) if net is not None else None,
        "roi_net_raw": roi_net,
        "roi_net_eth": from_wei(roi_net) if roi_net is not None else None,
        "roi_bps": round(roi_net * 10_000 / basis)
        if roi_net is not None and basis
        else None,
        "median_wallet_roi_bps": median_int(rois),
        "median_holding_seconds": median_int(holds),
        "curve_wallets": phases["curve"],
        "v4_wallets": phases["v4"],
        "transfer_wallets": phases["transfer"],
        "unknown_wallets": phases["unknown"],
    }


def analyze_entry_cohorts(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    bucket: int = 60,
    output: str | None = None,
) -> dict[str, Any]:
    """Group position rows by first-activity UTC bucket and aggregate performance."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if bucket < 1:
        raise ValueError("Cohort bucket must be positive")
    path = f"analysis/positions-{minutes}/positions.csv"
    if not store.exists(path):
        raise InvariantError(
            f"Missing entry-cohort evidence {path}; run analyze positions {minutes}"
        )
    position_rows = store.read_csv(path)
    if not position_rows:
        raise InvariantError(f"Position analysis produced no wallets for {minutes}m")
    rows = []
    unbucketable_rows = []
    for row in position_rows:
        first = _float(row.get("first_activity_seconds"))
        if first is None:
            unbucketable_rows.append(row)
            continue
        entry_ts = profile.start_timestamp + int(first)
        bucket_start = (entry_ts // bucket) * bucket
        unrealized_raw = _optional_int(row.get("unrealized_quote_raw"))
        net_raw = _optional_int(row.get("net_quote_raw"))
        rows.append(
            {
                "wallet": row["wallet"],
                "entry_bucket": bucket_start,
                "entry_timestamp": entry_ts,
                "entry_utc": utc(bucket_start),
                "entry_phase": row.get("entry_phase", "unknown"),
                "open": str(row.get("open", "")).lower() == "true",
                "tokens_in_raw": _int(row.get("tokens_in_raw")),
                "tokens_in": from_wei(_int(row.get("tokens_in_raw")), profile.decimals),
                "tokens_end_raw": _int(row.get("tokens_end_raw")),
                "tokens_end": from_wei(
                    _int(row.get("tokens_end_raw")), profile.decimals
                ),
                "basis_deployed_raw": _int(row.get("basis_deployed_raw")),
                "basis_deployed_eth": from_wei(_int(row.get("basis_deployed_raw"))),
                "realized_quote_raw": _int(row.get("realized_quote_raw")),
                "realized_quote_eth": from_wei(_int(row.get("realized_quote_raw"))),
                "sale_pnl_raw": _int(row.get("sale_pnl_raw")),
                "sale_pnl_eth": from_wei(_int(row.get("sale_pnl_raw"))),
                "unrealized_quote_raw": unrealized_raw,
                "unrealized_quote_eth": (
                    from_wei(unrealized_raw) if unrealized_raw is not None else None
                ),
                "gas_quote_raw": _int(row.get("gas_quote_raw")),
                "gas_quote_eth": from_wei(_int(row.get("gas_quote_raw"))),
                "net_quote_raw": net_raw,
                "net_quote_eth": from_wei(net_raw) if net_raw is not None else None,
                "roi_bps": _optional_int(row.get("net_roi_bps")),
                "holding_seconds": _optional_int(row.get("holding_seconds")),
            }
        )
    if not rows:
        raise InvariantError("No wallets with entry timing for entry-cohort analysis")
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row["entry_bucket"], []).append(row)
    cohorts = []
    for bucket_start in sorted(buckets):
        selected = buckets[bucket_start]
        cohorts.append(
            {
                "bucket": bucket_start,
                "start_timestamp": bucket_start,
                "start_utc": utc(bucket_start),
                "before_launch": any(
                    row["entry_timestamp"] < profile.start_timestamp for row in selected
                ),
                **_aggregate(selected, profile),
            }
        )
    unbucketable_realized = sum(
        _int(row.get("realized_quote_raw")) for row in unbucketable_rows
    )
    unbucketable_gas = sum(_int(row.get("gas_quote_raw")) for row in unbucketable_rows)
    unbucketable_tokens = sum(
        _int(row.get("tokens_end_raw")) for row in unbucketable_rows
    )
    unbucketable_unrealized = (
        sum(_int(row.get("unrealized_quote_raw")) for row in unbucketable_rows)
        if all(
            row.get("unrealized_quote_raw") not in (None, "")
            for row in unbucketable_rows
        )
        else None
    )
    unbucketable_net = (
        sum(_int(row.get("net_quote_raw")) for row in unbucketable_rows)
        if all(row.get("net_quote_raw") not in (None, "") for row in unbucketable_rows)
        else None
    )
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "bucket_seconds": bucket,
        "bucket_alignment": "UTC epoch boundaries",
        "wallets": len(rows),
        "unbucketable_wallets": len(unbucketable_rows),
        "unbucketable_net_quote_raw": unbucketable_net,
        "unbucketable_net_quote_eth": from_wei(unbucketable_net)
        if unbucketable_net is not None
        else None,
        "unbucketable_realized_quote_raw": unbucketable_realized,
        "unbucketable_realized_quote_eth": from_wei(unbucketable_realized),
        "unbucketable_unrealized_quote_raw": unbucketable_unrealized,
        "unbucketable_unrealized_quote_eth": from_wei(unbucketable_unrealized)
        if unbucketable_unrealized is not None
        else None,
        "unbucketable_gas_quote_raw": unbucketable_gas,
        "unbucketable_gas_quote_eth": from_wei(unbucketable_gas),
        "unbucketable_tokens_end_raw": unbucketable_tokens,
        "unbucketable_tokens_end": from_wei(unbucketable_tokens, profile.decimals),
        "cohorts": len(cohorts),
        "first_entry_utc": cohorts[0]["start_utc"],
        "last_entry_utc": cohorts[-1]["start_utc"],
        "largest_cohort": max(
            cohorts, key=lambda row: (row["wallets"], -row["bucket"])
        )["wallets"],
        "rows": cohorts,
        "top_by_net": sorted(
            cohorts, key=lambda row: (-(row["net_quote_eth"] or 0.0), row["bucket"])
        )[:10],
        "top_by_roi": sorted(
            (row for row in cohorts if row["roi_bps"] is not None),
            key=lambda row: (-row["roi_bps"], row["bucket"]),
        )[:10],
        "top_by_wallets": sorted(
            cohorts, key=lambda row: (-row["wallets"], row["bucket"])
        )[:10],
    }
    out = output or f"analysis/entry-cohorts-{minutes}"
    store.write_csv(f"{out}/cohorts.csv", cohorts, fields=COHORT_FIELDS)
    store.write_csv(f"{out}/wallets.csv", rows, fields=WALLET_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
