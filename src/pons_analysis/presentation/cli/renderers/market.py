"""Trajectory, candle, holder, and order-flow renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import (
    _fmt_net,
    _fmt_number,
    _fmt_price,
    _key_value,
    _short_address,
    _sparkline,
)


def _trajectory_tables(summary: dict, top: int) -> None:
    replay = summary.get("reserve_replay") or {}
    impact = summary.get("execution_impact") or {}
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m trajectory[/bold]"
        )
    )
    _key_value(
        "Trajectory",
        {
            "trades": f"{summary.get('trades', 0)} "
            f"({summary.get('curve_trades', 0)} curve / "
            f"{summary.get('v4_swaps', 0)} v4)",
            "buys / sells": f"{summary.get('buys', 0)} / {summary.get('sells', 0)}",
            "volume ETH": _fmt_number(summary.get("volume_eth")),
            "buy ETH": _fmt_number(summary.get("buy_volume_eth")),
            "sell ETH": _fmt_number(summary.get("sell_volume_eth")),
            "first price": _fmt_price(summary.get("first_price_eth")),
            "last price": _fmt_price(summary.get("last_price_eth")),
            "peak price": _fmt_price(summary.get("peak_price_eth")),
            "low price": _fmt_price(summary.get("low_price_eth")),
            "max drawdown bps": summary.get("max_drawdown_bps", 0),
            "liquidity changes": replay.get("liquidity_changes", 0),
            "reserve drift wei": replay.get("max_drift_raw", 0),
            "continuity breaks": replay.get("continuity_breaks", 0),
            "seed quote delta wei": replay.get("seed_quote_delta_raw"),
        },
    )
    _key_value(
        "V4 execution impact",
        {
            "impact trades": f"{impact.get('trades', 0)} / "
            f"{summary.get('v4_swaps', 0)} "
            f"({_fmt_number(impact.get('coverage_bps'), 0)} bps coverage)",
            "median abs bps": _fmt_number(impact.get("median_abs_bps"), 0),
            "p90 abs bps": _fmt_number(impact.get("p90_abs_bps"), 0),
            "max abs bps": _fmt_number(impact.get("max_abs_bps"), 0),
            "volume-weighted bps": _fmt_number(
                impact.get("volume_weighted_abs_bps"), 0
            ),
        },
    )
    spark = _sparkline(summary.get("price_samples") or [])
    if spark:
        console.print(f"Price path: [cyan]{spark}[/cyan]")

    rows = (summary.get("top_by_volume") or [])[:top]
    table = Table(title=f"Top {len(rows)} trades by quote volume")
    table.add_column("Time", style="cyan")
    table.add_column("Phase")
    table.add_column("Side")
    table.add_column("Quote ETH", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Pool after", justify="right")
    table.add_column("Impact bps", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("utc", ""))[11:19],
            row.get("phase", ""),
            row.get("side", ""),
            _fmt_number(row.get("quote_amount")),
            _fmt_number(row.get("token_amount"), 2),
            _fmt_price(row.get("execution_price_eth")),
            _fmt_price(row.get("pool_price_eth_after")),
            _fmt_number(row.get("price_impact_abs_bps"), 0),
        )
    console.print(table)

    impact_rows = (impact.get("top_by_impact") or [])[:top]
    if impact_rows:
        table = Table(title=f"Top {len(impact_rows)} v4 execution impacts")
        table.add_column("Time", style="cyan")
        table.add_column("Side")
        table.add_column("Quote ETH", justify="right")
        table.add_column("Impact bps", justify="right")
        table.add_column("Execution", justify="right")
        table.add_column("Pre mid", justify="right")
        for row in impact_rows:
            table.add_row(
                str(row.get("utc", ""))[11:19],
                row.get("side", ""),
                _fmt_number(row.get("quote_amount")),
                _fmt_number(row.get("price_impact_abs_bps"), 0),
                _fmt_price(row.get("execution_price_eth")),
                _fmt_price(row.get("pre_price_eth")),
            )
        console.print(table)

    if replay.get("available"):
        _key_value(
            "V4 reserve replay",
            {
                "initial quote": _fmt_number(replay.get("initial_quote_eth")),
                "initial tokens": _fmt_number(replay.get("initial_token_amount"), 2),
                "final quote": _fmt_number(replay.get("final_quote_eth")),
                "final tokens": _fmt_number(replay.get("final_token_amount"), 2),
                "curve seed quote": _fmt_number(replay.get("curve_seed_quote_eth")),
                "seed reconciled": replay.get("seed_quote_reconciled"),
                "continuity reconciled": replay.get("continuity_reconciled"),
            },
        )
        if replay.get("reconciled"):
            console.print("[green]V4 reserve state and curve seed reconcile.[/green]")
        else:
            console.print("[red]Reserve replay does not reconcile.[/red]")
    else:
        console.print(
            "[dim]No v4 swaps in this window; reserve replay unavailable.[/dim]"
        )


def _candles_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m candles[/bold]"
        )
    )
    _key_value(
        "OHLCV",
        {
            "bucket s": summary.get("bucket_seconds", 0),
            "candles": summary.get("candles", 0),
            "partial": summary.get("partial_candles", 0),
            "trades": summary.get("trades", 0),
            "volume ETH": _fmt_number(summary.get("volume_eth")),
            "VWAP": _fmt_price(summary.get("vwap_eth")),
            "FDV first": _fmt_number(summary.get("fdv_first_eth")),
            "FDV last": _fmt_number(summary.get("fdv_last_eth")),
            "FDV peak": _fmt_number(summary.get("fdv_peak_eth")),
            "first / last": f"{_fmt_price(summary.get('first_price_eth'))} / "
            f"{_fmt_price(summary.get('last_price_eth'))}",
            "realized vol bps": (
                summary.get("realized_volatility_bps")
                if summary.get("realized_volatility_bps") is not None
                else "—"
            ),
            "max range bps": (
                summary.get("max_range_bps")
                if summary.get("max_range_bps") is not None
                else "—"
            ),
            "profile bins": summary.get("volume_profile_bins", 0),
        },
    )
    rows = (summary.get("top_by_volume") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} candles by quote volume")
        table.add_column("Start", style="cyan")
        table.add_column("Open", justify="right")
        table.add_column("High", justify="right")
        table.add_column("Low", justify="right")
        table.add_column("Close", justify="right")
        table.add_column("Volume ETH", justify="right")
        table.add_column("Trades", justify="right")
        table.add_column("Change bps", justify="right")
        table.add_column("Range bps", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("start_utc", ""))[11:19],
                _fmt_price(row.get("open_price_eth")),
                _fmt_price(row.get("high_price_eth")),
                _fmt_price(row.get("low_price_eth")),
                _fmt_price(row.get("close_price_eth")),
                _fmt_number(row.get("volume_eth")),
                str(row.get("trades", 0)),
                _fmt_number(row.get("price_change_bps"), 0),
                _fmt_number(row.get("range_bps"), 0),
            )
        console.print(table)

    profile_rows = summary.get("volume_profile") or []
    if profile_rows:
        table = Table(title="Volume profile (log price bins)")
        table.add_column("Bin", justify="right")
        table.add_column("Price low", justify="right")
        table.add_column("Price high", justify="right")
        table.add_column("Trades", justify="right")
        table.add_column("Volume ETH", justify="right")
        table.add_column("Share bps", justify="right")
        for row in profile_rows:
            table.add_row(
                str(row.get("bin", "")),
                _fmt_price(row.get("price_low_eth")),
                _fmt_price(row.get("price_high_eth")),
                str(row.get("trades", 0)),
                _fmt_number(row.get("volume_eth")),
                str(row.get("volume_share_bps", 0)),
            )
        console.print(table)


def _holders_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m holders[/bold]"
        )
    )
    _key_value(
        "Concentration",
        {
            "bucket s": summary.get("bucket_seconds", 0),
            "buckets": summary.get("buckets", 0),
            "transfers": summary.get("transfers", 0),
            "first / last holders": f"{summary.get('first_holders', 0)} / "
            f"{summary.get('last_holders', 0)}",
            "peak holders": f"{summary.get('peak_holders', 0)} "
            f"({str(summary.get('peak_utc', ''))[11:19]})",
            "net change": summary.get("net_holder_change", 0),
            "new / exited": f"{summary.get('new_holders', 0)} / "
            f"{summary.get('exited_holders', 0)}",
            "last top1 bps": _fmt_number(summary.get("last_top1_bps"), 0),
            "last top10 bps": _fmt_number(summary.get("last_top10_bps"), 0),
            "last HHI bps": _fmt_number(summary.get("last_hhi_bps"), 0),
            "max top1 bps": _fmt_number(summary.get("max_top1_bps"), 0),
            "max HHI bps": _fmt_number(summary.get("max_hhi_bps"), 0),
        },
    )
    rows = (summary.get("top_by_concentration") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} concentration snapshots")
        table.add_column("Start", style="cyan")
        table.add_column("Holders", justify="right")
        table.add_column("New", justify="right")
        table.add_column("Exited", justify="right")
        table.add_column("Top1 bps", justify="right")
        table.add_column("Top10 bps", justify="right")
        table.add_column("HHI bps", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("start_utc", ""))[11:19],
                str(row.get("holders", 0)),
                str(row.get("new_holders", 0)),
                str(row.get("exited_holders", 0)),
                _fmt_number(row.get("top1_bps"), 0),
                _fmt_number(row.get("top10_bps"), 0),
                _fmt_number(row.get("hhi_bps"), 0),
            )
        console.print(table)


def _flow_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m order flow[/bold]"
        )
    )
    _key_value(
        "Flow",
        {
            "bucket s": summary.get("bucket_seconds", 0),
            "buckets": summary.get("buckets", 0),
            "trades": summary.get("trades", 0),
            "buy / sell ETH": f"{_fmt_number(summary.get('buy_volume_eth'))} / "
            f"{_fmt_number(summary.get('sell_volume_eth'))}",
            "volume ETH": _fmt_number(summary.get("volume_eth")),
            "net ETH": _fmt_net(summary.get("net_flow_eth")),
            "imbalance bps": _fmt_number(summary.get("flow_imbalance_bps"), 0),
            "avg trade ETH": _fmt_number(summary.get("avg_trade_eth")),
            "median trade ETH": _fmt_number(summary.get("median_trade_eth")),
            "p90 trade ETH": _fmt_number(summary.get("p90_trade_eth")),
            "max trade ETH": _fmt_number(summary.get("max_trade_eth")),
            "top-decile share bps": _fmt_number(summary.get("top_decile_share_bps"), 0),
        },
    )
    for label, key in (
        ("Top net buyers", "top_buyers"),
        ("Top net sellers", "top_sellers"),
    ):
        rows = (summary.get(key) or [])[:top]
        if not rows:
            continue
        table = Table(title=f"{label} ({len(rows)})")
        table.add_column("Wallet", style="cyan")
        table.add_column("Net ETH", justify="right")
        table.add_column("Buy ETH", justify="right")
        table.add_column("Sell ETH", justify="right")
        table.add_column("Trades", justify="right")
        for row in rows:
            table.add_row(
                _short_address(row["wallet"]),
                _fmt_net(row.get("net_flow_eth")),
                _fmt_number(row.get("buy_volume_eth")),
                _fmt_number(row.get("sell_volume_eth")),
                str(row.get("trades", 0)),
            )
        console.print(table)

    rows = (summary.get("top_by_volume") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} buckets by gross flow")
        table.add_column("Start", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Buy ETH", justify="right")
        table.add_column("Sell ETH", justify="right")
        table.add_column("Net ETH", justify="right")
        table.add_column("Imbalance bps", justify="right")
        table.add_column("Top-decile bps", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("start_utc", ""))[11:19],
                str(row.get("trades", 0)),
                _fmt_number(row.get("buy_volume_eth")),
                _fmt_number(row.get("sell_volume_eth")),
                _fmt_net(row.get("net_flow_eth")),
                _fmt_number(row.get("flow_imbalance_bps"), 0),
                _fmt_number(row.get("top_decile_share_bps"), 0),
            )
        console.print(table)
