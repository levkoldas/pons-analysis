"""Position, transaction, and lot inventory checks."""

import statistics

from pons_analysis.validation.derived.context import ValidationContext, require_summary


def run(ctx: ValidationContext) -> None:
    positions = ctx.positions
    if not positions:
        ctx.check("positions rows", False, "positions.csv missing or empty")
    else:
        ctx.check("positions rows", True, f"{len(positions)} wallets")
    transactions = ctx.transactions
    positions_summary = ctx.summaries.get("positions", {})
    require_summary(ctx, ctx.summaries.get("positions"), positions, "position")
    position_totals = ctx.position_totals
    if positions_summary:
        ctx.check(
            "position wallet count",
            positions_summary.get("wallets") == len(positions),
            f"{positions_summary.get('wallets')} != {len(positions)}",
        )
    if positions:
        position_gas = sum(int(row["gas_quote_raw"]) for row in positions)
        ctx.check(
            "position gas total",
            position_gas == position_totals.get("gas_quote_raw"),
            f"{position_gas} != {position_totals.get('gas_quote_raw')}",
        )
    if transactions:
        ctx.check(
            "transaction row count",
            positions_summary.get("transactions") == len(transactions),
            f"{positions_summary.get('transactions')} != {len(transactions)}",
        )
        transaction_gas = sum(int(row["gas_quote_raw"]) for row in transactions)
        ctx.check(
            "transaction gas rows",
            transaction_gas == positions_summary.get("trade_transaction_gas_raw"),
            f"{transaction_gas} != "
            f"{positions_summary.get('trade_transaction_gas_raw')}",
        )
        ctx.check(
            "position gas split",
            positions_summary.get("trade_transaction_gas_raw", 0)
            + positions_summary.get("non_trade_transaction_gas_raw", 0)
            == position_totals.get("gas_quote_raw"),
            "trade + non-trade transaction gas != total gas",
        )
    lots = ctx.lots
    if positions:
        ctx.check(
            "lot rows",
            ctx.store.exists(f"analysis/positions-{ctx.minutes}/lots.csv"),
            "lots.csv missing",
        )
        lots_by_wallet: dict[str, list[int]] = {}
        for row in lots:
            if row.get("acquired_timestamp") in (None, ""):
                continue
            lots_by_wallet.setdefault(row["wallet"].lower(), []).append(
                int(row["acquired_timestamp"])
            )
        end = positions_summary.get("end_timestamp_exclusive")
        lot_mismatches = []
        row_medians = []
        row_oldest = []
        for row in positions:
            wallet = row["wallet"].lower()
            ages = (
                [
                    max(0, int(end) - acquired)
                    for acquired in lots_by_wallet.get(wallet, [])
                ]
                if end is not None
                else []
            )
            median_age = round(statistics.median(ages)) if ages else None
            oldest_age = max(ages) if ages else None
            if median_age is not None:
                row_medians.append(median_age)
            if oldest_age is not None:
                row_oldest.append(oldest_age)
            expected = (
                str(len(ages)),
                "" if median_age is None else str(median_age),
                "" if oldest_age is None else str(oldest_age),
            )
            actual = (
                row.get("remaining_lots", ""),
                row.get("median_lot_age_seconds", ""),
                row.get("oldest_lot_age_seconds", ""),
            )
            if actual != expected:
                lot_mismatches.append(wallet)
        ctx.check(
            "position lot age fields",
            not lot_mismatches,
            ", ".join(lot_mismatches[:5]),
        )
        lots_mark: dict[str, list[int]] = {}
        for row in lots:
            if row.get("mark_value_raw") not in (None, ""):
                lots_mark.setdefault(row["wallet"].lower(), []).append(
                    int(row["mark_value_raw"])
                )
        basis_mismatches = []
        net_mismatches = []
        for row in positions:
            unrealized = row.get("unrealized_quote_raw")
            if unrealized in (None, ""):
                continue
            wallet = row["wallet"].lower()
            marks = lots_mark.get(wallet, [])
            market = int(unrealized) + int(row["cost_basis_remaining_raw"])
            if abs(market - sum(marks)) > max(1, len(marks)):
                basis_mismatches.append(wallet)
            net = row.get("net_quote_raw")
            if net not in (None, "") and int(net) != (
                int(row["realized_quote_raw"])
                + int(unrealized)
                - int(row["gas_quote_raw"])
            ):
                net_mismatches.append(wallet)
        ctx.check(
            "position unrealized basis",
            not basis_mismatches,
            ", ".join(basis_mismatches[:5]),
        )
        ctx.check(
            "position net identity",
            not net_mismatches,
            ", ".join(net_mismatches[:5]),
        )
        inventory_age = positions_summary.get("inventory_age") or {}
        ctx.check(
            "inventory age summary",
            inventory_age.get("remaining_lots") == len(lots)
            and inventory_age.get("median_wallet_lot_age_seconds")
            == (round(statistics.median(row_medians)) if row_medians else None)
            and inventory_age.get("oldest_lot_age_seconds")
            == (max(row_oldest) if row_oldest else None),
            "inventory age summary disagrees with lots/positions",
        )
        priced_lots = [
            row for row in lots if row.get("unrealized_pnl_raw") not in (None, "")
        ]
        lot_extremes = positions_summary.get("lot_extremes") or {}

        def lot_key(row: dict[str, str]) -> tuple[int, str, int]:
            return (
                int(row["unrealized_pnl_raw"]),
                row["wallet"],
                int(row["lot_index"]),
            )

        worst = sorted(priced_lots, key=lot_key)[:10]
        best = sorted(
            priced_lots,
            key=lambda row: (
                -int(row["unrealized_pnl_raw"]),
                row["wallet"],
                int(row["lot_index"]),
            ),
        )[:10]
        expected_worst = [
            (
                row["wallet"],
                int(row["lot_index"]),
                int(row["unrealized_pnl_raw"]),
                int(row["cost_raw"]),
                int(row["mark_value_raw"]),
                int(row["age_seconds"]),
            )
            for row in worst
        ]
        expected_best = [
            (
                row["wallet"],
                int(row["lot_index"]),
                int(row["unrealized_pnl_raw"]),
                int(row["cost_raw"]),
                int(row["mark_value_raw"]),
                int(row["age_seconds"]),
            )
            for row in best
        ]
        actual_worst = [
            (
                row.get("wallet"),
                int(row["lot_index"]),
                int(row["unrealized_pnl_raw"]),
                int(row["cost_raw"]),
                int(row["mark_value_raw"]),
                int(row["age_seconds"]),
            )
            for row in lot_extremes.get("worst_unrealized", [])
        ]
        actual_best = [
            (
                row.get("wallet"),
                int(row["lot_index"]),
                int(row["unrealized_pnl_raw"]),
                int(row["cost_raw"]),
                int(row["mark_value_raw"]),
                int(row["age_seconds"]),
            )
            for row in lot_extremes.get("best_unrealized", [])
        ]
        ctx.check(
            "lot unrealized extremes",
            actual_worst == expected_worst and actual_best == expected_best,
            "summary lot extremes disagree with lots.csv",
        )
        buckets = positions_summary.get("inventory_age_buckets") or []
        bucket_tokens = sum(int(row.get("tokens_raw") or 0) for row in buckets)
        bucket_cost = sum(int(row.get("cost_raw") or 0) for row in buckets)
        ctx.check(
            "inventory age buckets",
            sum(int(row.get("lots") or 0) for row in buckets) == len(lots)
            and bucket_tokens
            == sum(int(row.get("tokens_end_raw") or 0) for row in positions)
            and bucket_cost == sum(int(row.get("cost_raw") or 0) for row in lots),
            "inventory age buckets disagree with lots/positions",
        )
