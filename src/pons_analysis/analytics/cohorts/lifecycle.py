"""Entry-phase and exit-status wallet cohorts from the position ledger.

The position ledger records the first observed token activity for each wallet as
``curve``, ``v4``, ``transfer``, or ``unknown``. This engine groups those rows by
entry phase and open/closed status, then aggregates exact integer PnL and ROI
fields. It does not infer intent or common ownership; the grouping is literal
evidence.
"""

from typing import Any

from pons_analysis.analytics.positions import median_int, read_positions, roi_bps
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore

PHASES = ("curve", "v4", "transfer", "unknown")
STATUSES = ("open", "closed")


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _aggregate(rows: list[dict[str, Any]], profile: Launch) -> dict[str, Any]:
    mark_available = all(row["unrealized_raw"] is not None for row in rows)
    capital = sum(row["basis_deployed_raw"] or 0 for row in rows)
    sold_basis = sum(row["sold_basis_raw"] or 0 for row in rows)
    realized = sum(row["realized_raw"] or 0 for row in rows)
    sale_pnl = sum(row["sale_pnl_raw"] or 0 for row in rows)
    gas = sum(row["gas_raw"] or 0 for row in rows)
    tokens_end = sum(row["tokens_end_raw"] for row in rows)
    unrealized = (
        sum(row["unrealized_raw"] or 0 for row in rows) if mark_available else None
    )
    net_quote = sum(row["net_raw"] or 0 for row in rows) if mark_available else None
    net_roi = sale_pnl + unrealized - gas if unrealized is not None else None
    rois = [row["net_roi_bps"] for row in rows if row["net_roi_bps"] is not None]
    holds = [
        row["holding_seconds"] for row in rows if row["holding_seconds"] is not None
    ]
    return {
        "wallets": len(rows),
        "open_wallets": sum(row["open"] for row in rows),
        "closed_wallets": sum(not row["open"] for row in rows),
        "tokens_end_raw": tokens_end,
        "tokens_end": from_wei(tokens_end, profile.decimals),
        "capital_deployed_raw": capital,
        "capital_deployed_eth": _eth(capital),
        "sold_basis_raw": sold_basis,
        "sold_basis_eth": _eth(sold_basis),
        "realized_quote_raw": realized,
        "realized_quote_eth": _eth(realized),
        "sale_pnl_raw": sale_pnl,
        "sale_pnl_eth": _eth(sale_pnl),
        "unrealized_quote_raw": unrealized,
        "unrealized_quote_eth": _eth(unrealized),
        "gas_quote_raw": gas,
        "gas_quote_eth": _eth(gas),
        "net_quote_raw": net_quote,
        "net_quote_eth": _eth(net_quote),
        "net_roi_raw": net_roi,
        "net_roi_eth": _eth(net_roi),
        "realized_roi_bps": roi_bps(sale_pnl, sold_basis),
        "net_roi_bps": roi_bps(net_roi, capital),
        "median_wallet_roi_bps": median_int(rois),
        "median_holding_seconds": median_int(holds),
    }


def _selected(
    rows: list[dict[str, Any]], phase: str, status: str
) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["entry_phase"] == phase]
    if status == "open":
        return [row for row in selected if row["open"]]
    if status == "closed":
        return [row for row in selected if not row["open"]]
    return selected


def _group_rows(
    rows: list[dict[str, Any]], profile: Launch
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    phases = []
    groups = []
    present = {row["entry_phase"] for row in rows}
    for phase in PHASES:
        if phase not in present:
            continue
        selected = _selected(rows, phase, "all")
        phases.append(
            {"entry_phase": phase, "status": "all", **_aggregate(selected, profile)}
        )
        for status in STATUSES:
            selected = _selected(rows, phase, status)
            if selected:
                groups.append(
                    {
                        "entry_phase": phase,
                        "status": status,
                        **_aggregate(selected, profile),
                    }
                )
    return phases, groups


def _wallet_rows(rows: list[dict[str, Any]], profile: Launch) -> list[dict[str, Any]]:
    phase_order = {phase: index for index, phase in enumerate(PHASES)}
    ordered = sorted(
        rows,
        key=lambda row: (
            phase_order.get(row["entry_phase"], len(PHASES)),
            0 if row["open"] else 1,
            -(row["net_roi_bps"] or 0),
            row["wallet"],
        ),
    )
    return [
        {
            "wallet": row["wallet"],
            "entry_phase": row["entry_phase"],
            "status": "open" if row["open"] else "closed",
            "tokens_end_raw": row["tokens_end_raw"],
            "tokens_end": from_wei(row["tokens_end_raw"], profile.decimals),
            "basis_deployed_raw": row["basis_deployed_raw"] or 0,
            "basis_deployed_eth": _eth(row["basis_deployed_raw"] or 0),
            "sold_basis_raw": row["sold_basis_raw"] or 0,
            "realized_quote_raw": row["realized_raw"],
            "realized_quote_eth": _eth(row["realized_raw"]),
            "sale_pnl_raw": row["sale_pnl_raw"] or 0,
            "sale_pnl_eth": _eth(row["sale_pnl_raw"] or 0),
            "unrealized_quote_raw": row["unrealized_raw"],
            "unrealized_quote_eth": _eth(row["unrealized_raw"]),
            "gas_quote_raw": row["gas_raw"],
            "gas_quote_eth": _eth(row["gas_raw"]),
            "net_quote_raw": row["net_raw"],
            "net_quote_eth": _eth(row["net_raw"]),
            "realized_roi_bps": row["realized_roi_bps"],
            "net_roi_bps": row["net_roi_bps"],
            "holding_seconds": row["holding_seconds"],
            "trade_count": row["trade_count"],
        }
        for row in ordered
    ]


GROUP_FIELDS = (
    "entry_phase",
    "status",
    "wallets",
    "open_wallets",
    "closed_wallets",
    "tokens_end_raw",
    "tokens_end",
    "capital_deployed_raw",
    "capital_deployed_eth",
    "sold_basis_raw",
    "realized_quote_raw",
    "sale_pnl_raw",
    "unrealized_quote_raw",
    "gas_quote_raw",
    "net_quote_raw",
    "net_roi_raw",
    "realized_roi_bps",
    "net_roi_bps",
    "median_wallet_roi_bps",
    "median_holding_seconds",
)

WALLET_FIELDS = (
    "wallet",
    "entry_phase",
    "status",
    "tokens_end_raw",
    "tokens_end",
    "basis_deployed_raw",
    "basis_deployed_eth",
    "sold_basis_raw",
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
    "realized_roi_bps",
    "net_roi_bps",
    "holding_seconds",
    "trade_count",
)


def analyze_lifecycle(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Group exact position rows by first observed entry phase and exit status."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    parsed = read_positions(store, minutes)
    rows = [dict(row, wallet=wallet) for wallet, row in parsed.items()]
    if not rows:
        raise InvariantError(f"Position analysis produced no rows for {minutes}m")
    stale = [
        row["wallet"]
        for row in rows
        if row["entry_phase"] is None or row["basis_deployed_raw"] is None
    ]
    if stale:
        raise InvariantError(
            "Position artifact predates lifecycle metrics; "
            f"re-run analyze positions {minutes}"
        )

    phases, groups = _group_rows(rows, profile)
    if sum(group["wallets"] for group in groups) != len(rows):
        raise InvariantError("Lifecycle groups do not cover every position row")
    if sum(phase["wallets"] for phase in phases) != len(rows):
        raise InvariantError("Lifecycle phases do not cover every position row")
    wallets = _wallet_rows(rows, profile)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "entry_scope": "first observed token activity",
        "roi_scope": (
            "return on sold or still-held FIFO basis; transferred-out and "
            "protocol-out basis are excluded from both numerator and denominator"
        ),
        "wallets": len(rows),
        "phases": phases,
        "groups": groups,
        "totals": _aggregate(rows, profile),
    }
    out = output or f"analysis/lifecycle-{minutes}"
    store.write_csv(f"{out}/wallets.csv", wallets, fields=WALLET_FIELDS)
    store.write_csv(f"{out}/groups.csv", groups, fields=GROUP_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
