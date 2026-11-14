"""Position performance and summary aggregation."""

import collections
import statistics
from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.analytics.market.trajectory import percentile
from pons_analysis.analytics.market.window import DEAD
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore

from .artifacts import _eth
from .models import TradeLeg


def roi_bps(numerator: int | None, denominator: int) -> int | None:
    if numerator is None or denominator <= 0:
        return None
    return round(numerator * 10_000 / denominator)


def median_int(values: list[Any]) -> int | None:
    return round(statistics.median(values)) if values else None


def _performance(rows: list[dict[str, Any]], *, mark_available: bool) -> dict[str, Any]:
    capital = sum(row["basis_deployed_raw"] for row in rows)
    sold_basis = sum(row["sold_basis_raw"] for row in rows)
    sale_pnl = sum(row["sale_pnl_raw"] for row in rows)
    gas = sum(row["gas_quote_raw"] for row in rows)
    unrealized = (
        sum(row["unrealized_quote_raw"] or 0 for row in rows)
        if mark_available
        else None
    )
    net_roi = sale_pnl + unrealized - gas if unrealized is not None else None
    rois = [row["net_roi_bps"] for row in rows if row["net_roi_bps"] is not None]
    realized_rois = [
        row["realized_roi_bps"] for row in rows if row["realized_roi_bps"] is not None
    ]
    holds = [
        row["holding_seconds"] for row in rows if row["holding_seconds"] is not None
    ]
    if mark_available:
        profitable = sum((row["net_quote_raw"] or 0) > 0 for row in rows)
        losing = sum((row["net_quote_raw"] or 0) < 0 for row in rows)
        flat = sum((row["net_quote_raw"] or 0) == 0 for row in rows)
    else:
        profitable = losing = flat = None
    return {
        "scope": (
            "return on sold or still-held FIFO basis; transferred-out and "
            "protocol-out basis are excluded from both numerator and denominator"
        ),
        "wallets": len(rows),
        "wallets_with_basis": sum(row["basis_deployed_raw"] > 0 for row in rows),
        "profitable_wallets": profitable,
        "losing_wallets": losing,
        "flat_wallets": flat,
        "open_wallets": sum(row["open"] for row in rows),
        "closed_wallets": sum(not row["open"] for row in rows),
        "capital_deployed_raw": capital,
        "capital_deployed_eth": _eth(capital),
        "sold_basis_raw": sold_basis,
        "sold_basis_eth": _eth(sold_basis),
        "sale_pnl_raw": sale_pnl,
        "sale_pnl_eth": _eth(sale_pnl),
        "unrealized_quote_raw": unrealized,
        "unrealized_quote_eth": _eth(unrealized),
        "gas_quote_raw": gas,
        "gas_quote_eth": _eth(gas),
        "net_roi_raw": net_roi,
        "net_roi_eth": _eth(net_roi),
        "realized_roi_bps": roi_bps(sale_pnl, sold_basis),
        "net_roi_bps": roi_bps(net_roi, capital),
        "median_wallet_roi_bps": median_int(rois),
        "median_realized_roi_bps": median_int(realized_rois),
        "median_holding_seconds": median_int(holds),
    }


def _pnl_histogram(net_values: list[int]) -> list[dict[str, Any]]:
    low, high = min(net_values), max(net_values)
    count = 20 if high > low else 1
    histogram_counts = [0] * count
    for value in net_values:
        index = (value - low) * count // (high - low) if high > low else 0
        histogram_counts[min(count - 1, max(0, index))] += 1
    histogram = []
    for index, bucket_count in enumerate(histogram_counts):
        lower = low + (high - low) * index // count if high > low else low
        upper = low + (high - low) * (index + 1) // count if high > low else high
        histogram.append(
            {
                "lower_net_raw": lower,
                "lower_net_eth": _eth(lower),
                "upper_net_raw": upper,
                "upper_net_eth": _eth(upper),
                "count": bucket_count,
            }
        )
    return histogram


def _summary(
    store: ArtifactStore,
    out: str,
    rows: list[dict[str, Any]],
    legs: list[TradeLeg],
    balances: collections.Counter[str],
    protocol: set[str],
    cohort: set[str],
    profile: Launch,
    mark: dict[str, Any] | None,
    *,
    transactions: list[dict[str, Any]],
    lots: list[dict[str, Any]],
    event_legs: int,
    minutes: int,
    start: int,
    end: int,
) -> dict[str, Any]:
    roles = {
        "curve": profile.curve,
        "manager": profile.manager,
        "router": profile.router,
        "hook": profile.hook,
        "factory": profile.factory,
        "dead": DEAD,
    }
    holdings = [
        {
            "role": role,
            "address": address,
            "tokens_raw": balances[address],
            "tokens": from_wei(balances[address], profile.decimals),
        }
        for role, address in roles.items()
        if address is not None
    ]
    circulating = sum(
        value
        for wallet, value in balances.items()
        if wallet not in protocol and wallet != ZERO
    )
    unaccounted = (
        profile.supply
        - circulating
        - sum(balances[address] for address in protocol if address != ZERO and address)
    )
    mark_available = mark is not None or all(
        row["unrealized_quote_raw"] is not None for row in rows
    )
    totals = {
        "realized_quote_raw": sum(row["realized_quote_raw"] for row in rows),
        "unrealized_quote_raw": (
            sum(row["unrealized_quote_raw"] or 0 for row in rows)
            if mark_available
            else None
        ),
        "gas_quote_raw": sum(row["gas_quote_raw"] for row in rows),
        "net_quote_raw": (
            sum(row["net_quote_raw"] or 0 for row in rows) if mark_available else None
        ),
        "cost_basis_remaining_raw": sum(
            row["cost_basis_remaining_raw"] for row in rows
        ),
        "sold_basis_raw": sum(row["sold_basis_raw"] for row in rows),
        "basis_deployed_raw": sum(row["basis_deployed_raw"] for row in rows),
    }
    totals["realized_quote_eth"] = _eth(totals["realized_quote_raw"])
    totals["unrealized_quote_eth"] = _eth(totals["unrealized_quote_raw"])
    totals["gas_quote_eth"] = _eth(totals["gas_quote_raw"])
    totals["net_quote_eth"] = _eth(totals["net_quote_raw"])
    trade_transaction_gas = sum(row["gas_quote_raw"] for row in transactions)
    gas_total = totals["gas_quote_raw"]
    if trade_transaction_gas > gas_total:
        raise InvariantError(
            "Trade transaction gas exceeds total observed gas: "
            f"{trade_transaction_gas} > {gas_total}"
        )
    non_trade_gas = gas_total - trade_transaction_gas
    roi_rows = [row for row in rows if row["net_roi_bps"] is not None]
    top_by_roi = sorted(
        roi_rows,
        key=lambda row: (
            -row["net_roi_bps"],
            -(row["net_quote_raw"] or 0),
            row["wallet"],
        ),
    )[:20]
    bottom_by_roi = sorted(
        roi_rows,
        key=lambda row: (row["net_roi_bps"], row["net_quote_raw"] or 0, row["wallet"]),
    )[:5]
    cohort_rows = [row for row in rows if row["cohort"]]
    tx_sizes = collections.Counter(leg.tx_hash for leg in legs)
    net_values = [
        row["net_quote_raw"] for row in rows if row["net_quote_raw"] is not None
    ]
    if net_values:
        profits = sorted((value for value in net_values if value > 0), reverse=True)
        gross_profit = sum(profits)
        gross_loss = -sum(value for value in net_values if value < 0)
        quantiles = {
            "p10_net_raw": percentile(net_values, 10),
            "p25_net_raw": percentile(net_values, 25),
            "p50_net_raw": percentile(net_values, 50),
            "p75_net_raw": percentile(net_values, 75),
            "p90_net_raw": percentile(net_values, 90),
        }
        histogram = _pnl_histogram(net_values)
        pnl_distribution = {
            "wallets": len(net_values),
            "profitable_wallets": len(profits),
            "losing_wallets": sum(value < 0 for value in net_values),
            "flat_wallets": sum(value == 0 for value in net_values),
            "gross_profit_raw": gross_profit,
            "gross_profit_eth": _eth(gross_profit),
            "gross_loss_raw": gross_loss,
            "gross_loss_eth": _eth(gross_loss),
            "profit_factor": (gross_profit / gross_loss if gross_loss else None),
            "profit_factor_bps": (
                round(gross_profit * 10_000 / gross_loss) if gross_loss else None
            ),
            "profit_factor_unbounded": gross_loss == 0 and gross_profit > 0,
            "median_net_raw": quantiles["p50_net_raw"],
            "median_net_eth": _eth(quantiles["p50_net_raw"]),
            **quantiles,
            **{
                name.replace("_raw", "_eth"): _eth(value)
                for name, value in quantiles.items()
            },
            "top10_profit_share_bps": (
                round(sum(profits[:10]) * 10_000 / gross_profit)
                if gross_profit
                else None
            ),
            "profit_hhi_bps": (
                sum(value * value for value in profits)
                * 10_000
                // (gross_profit * gross_profit)
                if gross_profit
                else None
            ),
            "histogram": histogram,
        }
    else:
        pnl_distribution = None
    unrealized_lots = [row for row in lots if row["unrealized_pnl_raw"] is not None]
    worst_lots = sorted(
        unrealized_lots,
        key=lambda row: (
            row["unrealized_pnl_raw"],
            row["wallet"],
            row["lot_index"],
        ),
    )[:10]
    best_lots = sorted(
        unrealized_lots,
        key=lambda row: (
            -row["unrealized_pnl_raw"],
            row["wallet"],
            row["lot_index"],
        ),
    )[:10]
    age_buckets = []
    for label, low, high in (
        ("0-60s", 0, 60),
        ("60-300s", 60, 300),
        ("300-900s", 300, 900),
        ("900s+", 900, None),
    ):
        selected = [
            row
            for row in lots
            if row["age_seconds"] >= low and (high is None or row["age_seconds"] < high)
        ]
        mark_values = [row["mark_value_raw"] for row in selected]
        pnl_values = [row["unrealized_pnl_raw"] for row in selected]
        age_buckets.append(
            {
                "bucket": label,
                "lots": len(selected),
                "tokens_raw": sum(row["tokens_raw"] for row in selected),
                "tokens": from_wei(
                    sum(row["tokens_raw"] for row in selected), profile.decimals
                ),
                "cost_raw": sum(row["cost_raw"] for row in selected),
                "cost_eth": from_wei(sum(row["cost_raw"] for row in selected)),
                "mark_value_raw": (
                    sum(mark_values)
                    if all(v is not None for v in mark_values)
                    else None
                ),
                "mark_value_eth": _eth(
                    sum(mark_values)
                    if all(v is not None for v in mark_values)
                    else None
                ),
                "unrealized_pnl_raw": (
                    sum(pnl_values) if all(v is not None for v in pnl_values) else None
                ),
                "unrealized_pnl_eth": _eth(
                    sum(pnl_values) if all(v is not None for v in pnl_values) else None
                ),
            }
        )
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "start_timestamp": start,
        "end_timestamp_exclusive": end,
        "start_utc": utc(start),
        "end_utc": utc(end),
        "cost_basis_method": "FIFO",
        "quote_unit": "native quote wei",
        "mark": mark,
        "trades": len(legs),
        "transactions": len(tx_sizes),
        "trade_transaction_gas_raw": trade_transaction_gas,
        "trade_transaction_gas_eth": _eth(trade_transaction_gas),
        "non_trade_transaction_gas_raw": non_trade_gas,
        "non_trade_transaction_gas_eth": _eth(non_trade_gas),
        "multi_swap_transactions": sum(size > 1 for size in tx_sizes.values()),
        "max_legs_per_transaction": max(tx_sizes.values(), default=0),
        "resolved_intermediary_legs": sum(
            leg.resolved_intermediary is not None for leg in legs
        ),
        "cross_wallet_legs": sum(leg.cross_wallet for leg in legs),
        "event_legs": event_legs,
        "protocol_only_legs": event_legs - len(legs),
        "buys": sum(leg.side == "buy" for leg in legs),
        "sells": sum(leg.side == "sell" for leg in legs),
        "wallets": len(rows),
        "supply_raw": profile.supply,
        "supply": from_wei(profile.supply, profile.decimals),
        "circulating_raw": circulating,
        "circulating": from_wei(circulating, profile.decimals),
        "protocol_holdings": holdings,
        "unaccounted_raw": unaccounted,
        "unaccounted": from_wei(unaccounted, profile.decimals),
        "reconciled": unaccounted == 0,
        "totals": totals,
        "performance": _performance(rows, mark_available=mark_available),
        "lot_extremes": {
            "worst_unrealized": worst_lots,
            "best_unrealized": best_lots,
        },
        "inventory_age_buckets": age_buckets,
        "inventory_age": {
            "remaining_lots": sum(row["remaining_lots"] for row in rows),
            "median_wallet_lot_age_seconds": median_int(
                [
                    row["median_lot_age_seconds"]
                    for row in rows
                    if row["median_lot_age_seconds"] is not None
                ]
            ),
            "oldest_lot_age_seconds": max(
                (
                    row["oldest_lot_age_seconds"]
                    for row in rows
                    if row["oldest_lot_age_seconds"] is not None
                ),
                default=None,
            ),
        },
        "pnl_distribution": pnl_distribution,
        "top_by_net": rows[:10],
        "top_by_roi": top_by_roi,
        "bottom_by_net": sorted(
            rows, key=lambda row: (row["net_quote_raw"] or 0, row["wallet"])
        )[:5],
        "bottom_by_roi": bottom_by_roi,
        "cohort": {
            "wallets": len(cohort_rows),
            "tokens_end_raw": sum(row["tokens_end_raw"] for row in cohort_rows),
            "tokens_end": sum(row["tokens_end"] for row in cohort_rows),
            "realized_quote_raw": sum(row["realized_quote_raw"] for row in cohort_rows),
            "realized_quote_eth": _eth(
                sum(row["realized_quote_raw"] for row in cohort_rows)
            ),
            "net_quote_raw": (
                sum(row["net_quote_raw"] or 0 for row in cohort_rows)
                if mark_available
                else None
            ),
            "net_quote_eth": (
                _eth(sum(row["net_quote_raw"] or 0 for row in cohort_rows))
                if mark_available
                else None
            ),
            "performance": _performance(cohort_rows, mark_available=mark_available),
        }
        if cohort
        else None,
    }
    store.write_json(f"{out}/summary.json", summary)
    return summary
