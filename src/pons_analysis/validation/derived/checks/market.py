"""Market, lifecycle, execution, and launch checks."""

import math

from pons_analysis.validation.derived.context import (
    ValidationContext,
    require_summary,
    wallet_set,
)


def run_execution(ctx: ValidationContext) -> None:
    execution = ctx.execution
    execution_summary = ctx.summaries.get("execution")
    require_summary(ctx, execution_summary, execution, "execution")
    if execution_summary is not None:
        ctx.check(
            "execution wallet count",
            execution_summary.get("wallets") == len(execution),
            f"{execution_summary.get('wallets')} != {len(execution)}",
        )
    if execution:
        ctx.subset("execution", execution)
        ctx.check(
            "execution attribution totals",
            int(execution_summary.get("attributed_trades") or 0)
            + int(execution_summary.get("unattributed_trades") or 0)
            == execution_summary.get("impact_trades"),
            "attributed + unattributed != impact trades",
        )
        trajectory_rows = ctx.trajectory
        impact_rows = [
            row
            for row in trajectory_rows
            if row.get("phase") == "v4"
            and row.get("price_impact_abs_bps") not in (None, "")
        ]
        ctx.check(
            "execution impact row count",
            len(impact_rows) == execution_summary.get("impact_trades"),
            f"{len(impact_rows)} != {execution_summary.get('impact_trades')}",
        )
        ctx.check(
            "execution wallet totals",
            sum(int(row.get("trades") or 0) for row in execution)
            == execution_summary.get("attributed_trades")
            and math.isclose(
                sum(float(row.get("volume_eth") or 0) for row in execution),
                float(execution_summary.get("volume_eth") or 0),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ),
            "execution wallet trades/volume differ from summary",
        )


def run_lifecycle(ctx: ValidationContext) -> None:
    lifecycle = ctx.lifecycle
    require_summary(ctx, ctx.summaries.get("lifecycle"), lifecycle, "lifecycle")
    if lifecycle:
        ctx.check(
            "lifecycle wallet coverage",
            wallet_set(lifecycle) == ctx.wallets,
            f"{len(wallet_set(lifecycle))} lifecycle vs {len(ctx.wallets)} positions",
        )
        lifecycle_summary = ctx.summaries.get("lifecycle", {})
        ctx.check(
            "lifecycle summary count",
            lifecycle_summary.get("wallets") == len(lifecycle),
            f"{lifecycle_summary.get('wallets')} != {len(lifecycle)}",
        )
        missing_gas = [
            row["wallet"] for row in lifecycle if not row.get("gas_quote_raw")
        ]
        lifecycle_gas = ctx.lifecycle_gas
        ctx.check(
            "lifecycle gas columns",
            not missing_gas,
            f"{len(missing_gas)} rows lack gas_quote_raw",
        )
        ctx.check(
            "lifecycle gas total",
            sum(lifecycle_gas.values()) == ctx.position_totals.get("gas_quote_raw"),
            f"{sum(lifecycle_gas.values())} != "
            f"{ctx.position_totals.get('gas_quote_raw')}",
        )
        position_by_wallet = {row["wallet"].lower(): row for row in ctx.positions}
        lifecycle_mismatches = []
        for row in lifecycle:
            position = position_by_wallet.get(row["wallet"].lower())
            if position is None:
                continue
            mismatch = False
            for key in (
                "realized_quote_eth",
                "unrealized_quote_eth",
                "gas_quote_eth",
                "net_quote_eth",
            ):
                left = None if row.get(key) in (None, "") else float(row[key])
                right = (
                    None if position.get(key) in (None, "") else float(position[key])
                )
                if left is None or right is None:
                    mismatch = left != right
                elif not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12):
                    mismatch = True
                if mismatch:
                    break
            if mismatch:
                lifecycle_mismatches.append(row["wallet"])
        ctx.check(
            "lifecycle PnL rows",
            not lifecycle_mismatches,
            ", ".join(lifecycle_mismatches[:5]),
        )
        lifecycle_totals = lifecycle_summary.get("totals") or {}
        position_totals = ctx.position_totals
        pnl_keys = (
            "realized_quote_raw",
            "unrealized_quote_raw",
            "net_quote_raw",
        )
        pnl_matches = all(
            (lifecycle_totals.get(key) is None and position_totals.get(key) is None)
            or (
                lifecycle_totals.get(key) is not None
                and position_totals.get(key) is not None
                and int(lifecycle_totals[key]) == int(position_totals[key])
            )
            for key in pnl_keys
        )
        ctx.check(
            "lifecycle PnL totals",
            pnl_matches,
            "lifecycle realized/unrealized/net differs from positions",
        )
        lifecycle_net = lifecycle_totals.get("net_quote_raw")
        ctx.check(
            "lifecycle net identity",
            lifecycle_net is None
            or int(lifecycle_net)
            == int(lifecycle_totals.get("realized_quote_raw") or 0)
            + int(lifecycle_totals.get("unrealized_quote_raw") or 0)
            - int(lifecycle_totals.get("gas_quote_raw") or 0),
            "lifecycle net != realized + unrealized - gas",
        )


def run_trajectory(ctx: ValidationContext) -> None:
    trajectory = ctx.trajectory
    trajectory_summary = ctx.summaries.get("trajectory")
    require_summary(ctx, trajectory_summary, trajectory, "trajectory")
    if trajectory_summary is not None:
        ctx.check(
            "trajectory row count",
            trajectory_summary.get("trades") == len(trajectory),
            f"{trajectory_summary.get('trades')} != {len(trajectory)}",
        )
    if trajectory:
        trajectory_summary = trajectory_summary or {}
        buys = [row for row in trajectory if row.get("side") == "buy"]
        sells = [row for row in trajectory if row.get("side") == "sell"]
        ctx.check(
            "trajectory summary totals",
            len(trajectory) == trajectory_summary.get("trades")
            and sum(int(row.get("quote_amount_raw") or 0) for row in trajectory)
            == int(trajectory_summary.get("volume_raw") or 0)
            and len(buys) == trajectory_summary.get("buys")
            and len(sells) == trajectory_summary.get("sells")
            and sum(int(row.get("quote_amount_raw") or 0) for row in buys)
            == int(trajectory_summary.get("buy_volume_raw") or 0)
            and sum(int(row.get("quote_amount_raw") or 0) for row in sells)
            == int(trajectory_summary.get("sell_volume_raw") or 0)
            and math.isclose(
                float(trajectory[0].get("price_eth") or 0),
                float(trajectory_summary.get("first_price_eth") or 0),
                rel_tol=1e-9,
                abs_tol=1e-18,
            )
            and math.isclose(
                float(trajectory[-1].get("price_eth") or 0),
                float(trajectory_summary.get("last_price_eth") or 0),
                rel_tol=1e-9,
                abs_tol=1e-18,
            )
            and sum(row.get("phase") == "v4" for row in trajectory)
            == trajectory_summary.get("v4_swaps")
            and sum(row.get("phase") == "curve" for row in trajectory)
            == trajectory_summary.get("curve_trades"),
            "trajectory summary totals disagree with trajectory rows",
        )


def run_candles(ctx: ValidationContext) -> None:
    candles = ctx.candles
    candle_summary = ctx.summaries.get("candles")
    require_summary(ctx, candle_summary, candles, "candle")
    if candle_summary is not None:
        ctx.check(
            "candle row count",
            candle_summary.get("candles") == len(candles),
            f"{candle_summary.get('candles')} != {len(candles)}",
        )
    if candles:
        trajectory_summary = ctx.summaries.get("trajectory", {})
        if trajectory_summary:
            ctx.check(
                "candle trajectory totals",
                candle_summary.get("trades") == trajectory_summary.get("trades")
                and candle_summary.get("volume_raw")
                == trajectory_summary.get("volume_raw")
                and candle_summary.get("buy_volume_raw")
                == trajectory_summary.get("buy_volume_raw")
                and candle_summary.get("sell_volume_raw")
                == trajectory_summary.get("sell_volume_raw")
                and math.isclose(
                    float(candle_summary.get("first_price_eth") or 0),
                    float(trajectory_summary.get("first_price_eth") or 0),
                    rel_tol=1e-9,
                    abs_tol=1e-18,
                )
                and math.isclose(
                    float(candle_summary.get("last_price_eth") or 0),
                    float(trajectory_summary.get("last_price_eth") or 0),
                    rel_tol=1e-9,
                    abs_tol=1e-18,
                ),
                "candle totals differ from trajectory",
            )
        ctx.check(
            "candle summary endpoints",
            math.isclose(
                float(candles[0].get("open_price_eth") or 0),
                float(candle_summary.get("first_price_eth") or 0),
                rel_tol=1e-9,
                abs_tol=1e-18,
            )
            and math.isclose(
                float(candles[-1].get("close_price_eth") or 0),
                float(candle_summary.get("last_price_eth") or 0),
                rel_tol=1e-9,
                abs_tol=1e-18,
            )
            and sum(int(row.get("trades") or 0) for row in candles)
            == candle_summary.get("trades")
            and sum(int(row.get("volume_raw") or 0) for row in candles)
            == int(candle_summary.get("volume_raw") or 0)
            and sum(int(row.get("buy_volume_raw") or 0) for row in candles)
            == int(candle_summary.get("buy_volume_raw") or 0)
            and sum(int(row.get("sell_volume_raw") or 0) for row in candles)
            == int(candle_summary.get("sell_volume_raw") or 0)
            and sum(str(row.get("partial", "")).lower() == "true" for row in candles)
            == candle_summary.get("partial_candles")
            and max(int(row.get("range_bps") or 0) for row in candles)
            == candle_summary.get("max_range_bps"),
            "candle summary endpoints disagree with candles",
        )


def run_holders(ctx: ValidationContext) -> None:
    holders = ctx.holders
    holder_summary = ctx.summaries.get("holders")
    require_summary(ctx, holder_summary, holders, "holder")
    if holder_summary is not None:
        ctx.check(
            "holder bucket count",
            holder_summary.get("buckets") == len(holders),
            f"{holder_summary.get('buckets')} != {len(holders)}",
        )
    if holders:
        holder_summary = holder_summary or {}
        last = holders[-1]
        ctx.check(
            "holder summary flows",
            sum(int(row.get("new_holders") or 0) for row in holders)
            == holder_summary.get("new_holders")
            and sum(int(row.get("exited_holders") or 0) for row in holders)
            == holder_summary.get("exited_holders")
            and sum(int(row.get("transfers") or 0) for row in holders)
            == holder_summary.get("transfers"),
            "holder summary flows disagree with timeline",
        )
        last_top1 = last.get("top1_bps")
        last_top10 = last.get("top10_bps")
        last_hhi = last.get("hhi_bps")
        ctx.check(
            "holder summary endpoints",
            int(holders[0].get("holders") or 0) == holder_summary.get("first_holders")
            and int(last.get("holders") or 0) == holder_summary.get("last_holders")
            and (
                (
                    last_top1 in (None, "")
                    and holder_summary.get("last_top1_bps") is None
                )
                or (
                    last_top1 not in (None, "")
                    and int(last_top1) == holder_summary.get("last_top1_bps")
                )
            )
            and (
                (
                    last_top10 in (None, "")
                    and holder_summary.get("last_top10_bps") is None
                )
                or (
                    last_top10 not in (None, "")
                    and int(last_top10) == holder_summary.get("last_top10_bps")
                )
            )
            and (
                (last_hhi in (None, "") and holder_summary.get("last_hhi_bps") is None)
                or (
                    last_hhi not in (None, "")
                    and int(last_hhi) == holder_summary.get("last_hhi_bps")
                )
            )
            and max(int(row.get("holders") or 0) for row in holders)
            == holder_summary.get("peak_holders"),
            "holder summary endpoints disagree with timeline",
        )


def run_flow(ctx: ValidationContext) -> None:
    flow = ctx.flow
    flow_summary = ctx.summaries.get("flow")
    require_summary(ctx, flow_summary, flow, "flow")
    if flow_summary is not None:
        ctx.check(
            "flow bucket count",
            flow_summary.get("buckets") == len(flow),
            f"{flow_summary.get('buckets')} != {len(flow)}",
        )
    if flow:
        flow_summary = flow_summary or {}
        flow_wallets = ctx.flow_wallets
        if flow_wallets:
            ctx.check(
                "flow wallet totals",
                sum(int(row.get("trades") or 0) for row in flow_wallets)
                == flow_summary.get("trades")
                and sum(int(row.get("buy_trades") or 0) for row in flow_wallets)
                == flow_summary.get("buys")
                and sum(int(row.get("sell_trades") or 0) for row in flow_wallets)
                == flow_summary.get("sells")
                and sum(int(row.get("buy_volume_raw") or 0) for row in flow_wallets)
                == int(flow_summary.get("buy_volume_raw") or 0)
                and sum(int(row.get("sell_volume_raw") or 0) for row in flow_wallets)
                == int(flow_summary.get("sell_volume_raw") or 0)
                and sum(int(row.get("gross_volume_raw") or 0) for row in flow_wallets)
                == int(flow_summary.get("volume_raw") or 0)
                and sum(int(row.get("net_flow_raw") or 0) for row in flow_wallets)
                == int(flow_summary.get("net_flow_raw") or 0),
                "flow wallet totals disagree with summary",
            )
        ctx.check(
            "flow summary totals",
            sum(int(row.get("trades") or 0) for row in flow)
            == flow_summary.get("trades")
            and sum(int(row.get("buys") or 0) for row in flow)
            == flow_summary.get("buys")
            and sum(int(row.get("sells") or 0) for row in flow)
            == flow_summary.get("sells")
            and sum(int(row.get("buy_volume_raw") or 0) for row in flow)
            == int(flow_summary.get("buy_volume_raw") or 0)
            and sum(int(row.get("sell_volume_raw") or 0) for row in flow)
            == int(flow_summary.get("sell_volume_raw") or 0)
            and sum(int(row.get("volume_raw") or 0) for row in flow)
            == int(flow_summary.get("volume_raw") or 0)
            and sum(int(row.get("net_flow_raw") or 0) for row in flow)
            == int(flow_summary.get("net_flow_raw") or 0)
            and sum(str(row.get("partial", "")).lower() == "true" for row in flow)
            == (flow_summary.get("partial_buckets") or 0),
            "flow summary totals disagree with buckets",
        )


def run_window(ctx: ValidationContext) -> None:
    rotations = ctx.rotations
    window_summary = ctx.window_summary
    start_timestamp = window_summary.get("start_timestamp")
    end_timestamp = window_summary.get("end_timestamp_exclusive")
    period_matches = start_timestamp is not None and end_timestamp == (
        start_timestamp + ctx.minutes * 60
    )
    if period_matches:
        for name in ("positions", "trajectory", "cohort"):
            period = ctx.summaries.get(name)
            if period is not None and (
                period.get("start_timestamp") != start_timestamp
                or period.get("end_timestamp_exclusive") != end_timestamp
            ):
                period_matches = False
                break
    if ctx.store.exists(f"analysis/window-{ctx.minutes}/summary.json"):
        ctx.check(
            "window period",
            period_matches,
            "window summary period does not match the validated window",
        )
        ctx.check(
            "window rotation count",
            window_summary.get("rotation_count") == len(rotations),
            f"{window_summary.get('rotation_count')} != {len(rotations)}",
        )
    if rotations:
        ctx.check(
            "window rotation totals",
            len(rotations) == window_summary.get("rotation_count")
            and len({row.get("source_wallet") for row in rotations})
            == window_summary.get("rotating_original_wallets")
            and math.isclose(
                sum(int(row.get("input_tokens_raw") or 0) for row in rotations)
                / 10**ctx.decimals,
                float(window_summary.get("rotated_tokens") or 0),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            and math.isclose(
                sum(int(row.get("received_tokens_raw") or 0) for row in rotations)
                / 10**ctx.decimals,
                float(window_summary.get("rotation_received_tokens") or 0),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            and min(int(row.get("seconds_after_migration") or 0) for row in rotations)
            == window_summary.get("rotation_first_seconds")
            and max(int(row.get("seconds_after_migration") or 0) for row in rotations)
            == window_summary.get("rotation_last_seconds"),
            "window rotation summary disagrees with rotations",
        )


def run_launch(ctx: ValidationContext) -> None:
    launch_routes = ctx.launch_routes
    launch_trades = ctx.launch_trades
    launch_holders = ctx.launch_holders
    launch_summary = ctx.launch_summary
    require_summary(
        ctx,
        launch_summary,
        launch_routes or launch_trades or launch_holders,
        "launch",
    )
    if launch_summary is not None:
        ctx.check(
            "launch route count",
            launch_summary.get("routes") == len(launch_routes),
            f"{launch_summary.get('routes')} != {len(launch_routes)}",
        )
        ctx.check(
            "launch holder count",
            launch_summary.get("holders") == len(launch_holders),
            f"{launch_summary.get('holders')} != {len(launch_holders)}",
        )
    if launch_routes and launch_summary is not None:
        if launch_trades:
            launch_all = launch_summary.get("all") or {}
            buys = [row for row in launch_trades if row.get("side") == "buy"]
            sells = [row for row in launch_trades if row.get("side") == "sell"]
            ctx.check(
                "launch summary totals",
                len(launch_trades) == launch_all.get("trades")
                and len(buys) == launch_all.get("buys")
                and len(sells) == launch_all.get("sells")
                and math.isclose(
                    sum(float(row.get("quote_eth") or 0) for row in launch_trades),
                    float(launch_all.get("volume_eth") or 0),
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and len({row.get("wallet") for row in launch_trades})
                == launch_all.get("wallets")
                and len({row.get("tx_from") for row in launch_trades})
                == launch_all.get("senders"),
                "launch summary totals disagree with trades",
            )
