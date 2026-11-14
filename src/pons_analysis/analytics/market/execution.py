"""Attribution of v4 execution impact to the token wallet.

Trajectory rows supply execution price and impact; position trade legs supply
the economic token wallet and gross quote volume. The two artifacts join on
``(tx_hash, log_index)``. Protocol-only swaps without a wallet leg remain
unattributed rather than being assigned to an arbitrary address.
"""

from typing import Any

from pons_analysis.analytics.market.trajectory import percentile
from pons_analysis.analytics.positions import median_int
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _int(value: Any) -> int:
    return int(value)


def _key(row: dict[str, str]) -> tuple[str, int]:
    return (row["tx_hash"].lower(), int(row["log_index"]))


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    volume = sum(row["quote_raw"] for row in rows)
    absolute = [row["impact_abs_bps"] for row in rows]
    signed = [row["impact_signed_bps"] for row in rows]
    weighted = (
        sum(row["impact_abs_bps"] * row["quote_raw"] for row in rows) / volume
        if volume
        else None
    )
    return {
        "trades": len(rows),
        "volume_raw": volume,
        "volume_eth": from_wei(volume),
        "median_signed_bps": median_int(signed),
        "median_abs_bps": median_int(absolute),
        "p90_abs_bps": percentile(absolute, 90),
        "max_abs_bps": max(absolute) if absolute else None,
        "volume_weighted_abs_bps": round(weighted) if weighted is not None else None,
    }


GROUP_FIELDS = (
    "dimension",
    "value",
    "trades",
    "volume_raw",
    "volume_eth",
    "median_signed_bps",
    "median_abs_bps",
    "p90_abs_bps",
    "max_abs_bps",
    "volume_weighted_abs_bps",
)

WALLET_FIELDS = (
    "wallet",
    "trades",
    "buy_trades",
    "sell_trades",
    "cross_wallet_trades",
    "volume_raw",
    "volume_eth",
    "median_signed_bps",
    "median_abs_bps",
    "p90_abs_bps",
    "max_abs_bps",
    "volume_weighted_abs_bps",
)


def analyze_execution(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Join v4 impact rows to trade legs and rank wallets by execution quality."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    trajectory_path = f"analysis/trajectory-{minutes}/trajectory.csv"
    legs_path = f"analysis/positions-{minutes}/trade_legs.csv"
    if not store.exists(trajectory_path):
        raise InvariantError(
            f"Missing execution evidence {trajectory_path}; "
            f"run analyze trajectory {minutes}"
        )
    if not store.exists(legs_path):
        raise InvariantError(
            f"Missing execution evidence {legs_path}; run analyze positions {minutes}"
        )
    trajectory = store.read_csv(trajectory_path)
    legs = store.read_csv(legs_path)

    leg_map: dict[tuple[str, int], dict[str, str]] = {}
    for row in legs:
        key = _key(row)
        if key in leg_map:
            raise InvariantError(
                "Multiple trade legs share a swap position; "
                "execution attribution is ambiguous"
            )
        leg_map[key] = row

    impact_rows = [
        row
        for row in trajectory
        if row.get("phase") == "v4"
        and row.get("price_impact_abs_bps") not in (None, "")
    ]

    attributed: list[dict[str, Any]] = []
    unattributed = 0
    for row in impact_rows:
        leg = leg_map.get(_key(row))
        if leg is None:
            unattributed += 1
            continue
        if leg.get("phase") != "v4" or leg.get("side") != row.get("side"):
            raise InvariantError(
                "Trajectory and trade leg disagree on phase or side for "
                f"{row['tx_hash']}:{row['log_index']}"
            )
        attributed.append(
            {
                "wallet": addr(leg["token_wallet"]),
                "side": row["side"],
                "quote_raw": _int(leg["quote_gross_raw"]),
                "impact_abs_bps": _int(row["price_impact_abs_bps"]),
                "impact_signed_bps": _int(row["price_impact_bps"]),
                "cross_wallet": str(leg.get("cross_wallet", "")).lower() == "true",
            }
        )

    by_wallet: dict[str, list[dict[str, Any]]] = {}
    for row in attributed:
        by_wallet.setdefault(row["wallet"], []).append(row)
    wallets = []
    for wallet, rows in by_wallet.items():
        stats = _stats(rows)
        stats.update(
            {
                "wallet": wallet,
                "buy_trades": sum(row["side"] == "buy" for row in rows),
                "sell_trades": sum(row["side"] == "sell" for row in rows),
                "cross_wallet_trades": sum(row["cross_wallet"] for row in rows),
            }
        )
        wallets.append(stats)
    wallets.sort(
        key=lambda row: (
            -(row["volume_weighted_abs_bps"] or 0),
            -(row["volume_raw"]),
            row["wallet"],
        )
    )

    groups = [
        {"dimension": "all", "value": "all", **_stats(attributed)},
        *[
            {"dimension": "side", "value": side, **_stats(selected)}
            for side in ("buy", "sell")
            if (selected := [row for row in attributed if row["side"] == side])
        ],
    ]
    if sum(row["trades"] for row in wallets) != len(attributed):
        raise InvariantError("Wallet attribution does not cover every trade")
    if sum(group["trades"] for group in groups[1:]) != len(attributed):
        raise InvariantError("Execution side groups do not cover every trade")
    totals = _stats(attributed)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "scope": (
            "v4 execution impact attributed to the economic token wallet from "
            "trade_legs; protocol-only swaps remain unattributed"
        ),
        "trajectory_v4_swaps": sum(row.get("phase") == "v4" for row in trajectory),
        "impact_trades": len(impact_rows),
        "attributed_trades": len(attributed),
        "unattributed_trades": unattributed,
        "coverage_bps": (
            round(len(attributed) * 10_000 / len(impact_rows)) if impact_rows else None
        ),
        "wallets": len(wallets),
        **totals,
        "groups": groups,
        "top_by_weighted": wallets[:20],
        "top_by_max": sorted(
            wallets,
            key=lambda row: (
                -(row["max_abs_bps"] or 0),
                -row["volume_raw"],
                row["wallet"],
            ),
        )[:10],
    }
    out = output or f"analysis/execution-{minutes}"
    store.write_csv(f"{out}/wallets.csv", wallets, fields=WALLET_FIELDS)
    store.write_csv(f"{out}/groups.csv", groups, fields=GROUP_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
