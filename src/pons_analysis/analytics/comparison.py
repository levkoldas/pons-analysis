"""Cross-window comparison of already-derived analysis summaries."""

from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore

# (group, label, artifact, field path)
METRICS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("positions", "wallets", "positions", ("wallets",)),
    ("positions", "trades", "positions", ("trades",)),
    ("positions", "transactions", "positions", ("transactions",)),
    ("positions", "net ETH", "positions", ("totals", "net_quote_eth")),
    ("positions", "ROI bps", "positions", ("performance", "net_roi_bps")),
    ("positions", "gas ETH", "positions", ("totals", "gas_quote_eth")),
    (
        "positions",
        "PF",
        "positions",
        ("pnl_distribution", "profit_factor"),
    ),
    ("trajectory", "volume ETH", "trajectory", ("volume_eth",)),
    (
        "trajectory",
        "drawdown bps",
        "trajectory",
        ("max_drawdown_bps",),
    ),
    (
        "trajectory",
        "impact bps",
        "trajectory",
        ("execution_impact", "volume_weighted_abs_bps"),
    ),
    ("fees", "fee ETH", "fees", ("totals", "total_fee_eth")),
    ("fees", "burden bps", "fees", ("totals", "fee_burden_bps")),
    ("flow", "net flow", "flow", ("net_flow_eth",)),
    ("flow", "imbalance", "flow", ("flow_imbalance_bps",)),
    ("holders", "holders", "holders", ("last_holders",)),
    ("holders", "top10 bps", "holders", ("last_top10_bps",)),
    ("holders", "HHI bps", "holders", ("last_hhi_bps",)),
    ("lifecycle", "open", "lifecycle", ("totals", "open_wallets")),
    ("lifecycle", "closed", "lifecycle", ("totals", "closed_wallets")),
    ("lifecycle", "ROI bps", "lifecycle", ("totals", "net_roi_bps")),
    ("retention", "token ret bps", "retention", ("token_retention_bps",)),
    (
        "retention",
        "holder ret bps",
        "retention",
        ("holder_retention_bps",),
    ),
    ("cohorts", "cohorts", "entry-cohorts", ("cohorts",)),
    ("cohorts", "wallets", "entry-cohorts", ("wallets",)),
    ("routes", "routes", "route-performance", ("routes",)),
    ("routes", "routed wallets", "route-performance", ("wallets",)),
    (
        "routes",
        "unassigned",
        "route-performance",
        ("unassigned_wallets",),
    ),
    ("routes", "net ETH", "route-performance", ("net_quote_eth",)),
    ("routes", "basis ETH", "route-performance", ("basis_deployed_eth",)),
    ("routes", "ROI bps", "route-performance", ("net_roi_bps",)),
    ("routes", "fee ETH", "route-performance", ("total_fee_eth",)),
    ("routes", "fee burden bps", "route-performance", ("fee_burden_bps",)),
    ("routes", "retained", "route-performance", ("retained_wallets",)),
    (
        "routes",
        "retention bps",
        "route-performance",
        ("retention_bps",),
    ),
    (
        "clusters",
        "impact bps",
        "cluster-quality",
        ("execution_weighted_bps",),
    ),
    (
        "clusters",
        "burden bps",
        "cluster-quality",
        ("fee_burden_bps",),
    ),
    ("clusters", "gas ETH", "cluster-quality", ("gas_eth",)),
)


def _summary(store: ArtifactStore, name: str, minutes: int) -> dict[str, Any] | None:
    relative = f"analysis/{name}-{minutes}/summary.json"
    if not store.exists(relative):
        return None
    payload = store.read_json(relative)
    if not isinstance(payload, dict):
        raise InvariantError(f"Malformed summary {relative}")
    actual = payload.get("minutes")
    if actual is not None and actual != minutes:
        raise InvariantError(
            f"{relative} has window {actual}, expected {minutes}; re-run {name}"
        )
    return payload


def _field(payload: dict[str, Any], path: tuple[str, ...]) -> int | float | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _positions(store: ArtifactStore, minutes: int) -> dict[str, float | None]:
    rows = store.read_csv(f"analysis/positions-{minutes}/positions.csv")
    if not rows:
        raise InvariantError(
            f"analysis/positions-{minutes}/positions.csv missing or empty"
        )
    values = {}
    for row in rows:
        wallet = row["wallet"].lower()
        value = row.get("net_quote_eth")
        values[wallet] = None if value in (None, "") else float(value)
    return values


def compare_windows(
    store: ArtifactStore,
    profile: Launch,
    *,
    left_minutes: int,
    right_minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Compare two analyzed windows and write a deterministic JSON summary."""
    if left_minutes < 1 or right_minutes < 1:
        raise ValueError("Window durations must be positive")
    if left_minutes == right_minutes:
        raise ValueError("Choose two different window durations")
    left = _summary(store, "positions", left_minutes)
    right = _summary(store, "positions", right_minutes)
    if left is None:
        raise InvariantError(
            f"Missing positions-{left_minutes}; run analyze positions {left_minutes}"
        )
    if right is None:
        raise InvariantError(
            f"Missing positions-{right_minutes}; run analyze positions {right_minutes}"
        )
    names = sorted({item[2] for item in METRICS})
    summaries = {
        name: {
            left_minutes: _summary(store, name, left_minutes),
            right_minutes: _summary(store, name, right_minutes),
        }
        for name in names
    }
    metrics = []
    for group, label, name, path in METRICS:
        left_summary = summaries[name][left_minutes]
        right_summary = summaries[name][right_minutes]
        left_value = _field(left_summary, path) if left_summary is not None else None
        right_value = _field(right_summary, path) if right_summary is not None else None
        if left_value is None and right_value is None:
            continue
        delta = (
            right_value - left_value
            if left_value is not None and right_value is not None
            else None
        )
        delta_pct = (
            delta * 100 / abs(left_value)
            if delta is not None and left_value not in (None, 0)
            else None
        )
        metrics.append(
            {
                "group": group,
                "metric": label,
                "left": left_value,
                "right": right_value,
                "delta": delta,
                "delta_pct": delta_pct,
            }
        )
    left_positions = _positions(store, left_minutes)
    right_positions = _positions(store, right_minutes)
    overlap = set(left_positions) & set(right_positions)
    overlap_left_values = [left_positions[wallet] for wallet in overlap]
    overlap_right_values = [right_positions[wallet] for wallet in overlap]
    overlap_left = (
        sum(value for value in overlap_left_values if value is not None)
        if all(value is not None for value in overlap_left_values)
        else None
    )
    overlap_right = (
        sum(value for value in overlap_right_values if value is not None)
        if all(value is not None for value in overlap_right_values)
        else None
    )
    wallet_overlap = {
        "left_wallets": len(left_positions),
        "right_wallets": len(right_positions),
        "overlap_wallets": len(overlap),
        "left_only_wallets": len(set(left_positions) - overlap),
        "right_only_wallets": len(set(right_positions) - overlap),
        "overlap_bps": (
            round(len(overlap) * 10_000 / len(left_positions))
            if left_positions
            else None
        ),
        "overlap_net_left_eth": overlap_left,
        "overlap_net_right_eth": overlap_right,
        "overlap_net_delta_eth": (
            overlap_right - overlap_left
            if overlap_left is not None and overlap_right is not None
            else None
        ),
    }
    summary = {
        "profile": profile.name,
        "left_minutes": left_minutes,
        "right_minutes": right_minutes,
        "metrics": metrics,
        "wallet_overlap": wallet_overlap,
    }
    destination = output or f"analysis/comparison-{left_minutes}-{right_minutes}.json"
    store.write_json(destination, summary)
    return summary
