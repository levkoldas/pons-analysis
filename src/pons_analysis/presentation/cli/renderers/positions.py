"""Wallet position and launch-route renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import _fmt_net, _fmt_number, _key_value, _short_address


def _positions_tables(summary: dict, top: int, sort: str = "net") -> None:
    mark = summary.get("mark") or {}
    totals = summary.get("totals") or {}
    performance = summary.get("performance") or {}
    distribution = summary.get("pnl_distribution") or {}
    inventory_age = summary.get("inventory_age") or {}
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m positions[/bold]"
        )
    )
    _key_value(
        "Ledger",
        {
            "trades": f"{summary.get('trades', 0)} wallet legs "
            f"({summary.get('buys', 0)} buys / {summary.get('sells', 0)} sells) · "
            f"{summary.get('event_legs', 0)} swap events",
            "transactions": f"{summary.get('transactions', 0)} "
            f"({summary.get('multi_swap_transactions', 0)} multi-swap, "
            f"max {summary.get('max_legs_per_transaction', 0)} legs)",
            "router-resolved legs": summary.get("resolved_intermediary_legs", 0),
            "cross-wallet legs": summary.get("cross_wallet_legs", 0),
            "wallets": summary.get("wallets", 0),
            "mark ETH/token": _fmt_number(mark.get("price_eth_per_token"), 12),
            "realized ETH": _fmt_number(totals.get("realized_quote_eth")),
            "unrealized ETH": _fmt_number(totals.get("unrealized_quote_eth")),
            "gas ETH": _fmt_number(totals.get("gas_quote_eth")),
            "net ETH": _fmt_number(totals.get("net_quote_eth")),
            "supply": _fmt_number(summary.get("supply"), 0),
            "circulating": _fmt_number(summary.get("circulating"), 0),
            "cost basis": summary.get("cost_basis_method", ""),
        },
    )
    _key_value(
        "Performance",
        {
            "wallet ROI bps": _fmt_number(performance.get("net_roi_bps"), 0),
            "realized ROI bps": _fmt_number(performance.get("realized_roi_bps"), 0),
            "profitable / losing": (
                f"{performance.get('profitable_wallets')} / "
                f"{performance.get('losing_wallets')}"
                if performance.get("profitable_wallets") is not None
                and performance.get("losing_wallets") is not None
                else "—"
            ),
            "median ROI bps": _fmt_number(performance.get("median_wallet_roi_bps"), 0),
            "median hold s": _fmt_number(performance.get("median_holding_seconds"), 0),
            "open / closed": f"{performance.get('open_wallets', 0)} / "
            f"{performance.get('closed_wallets', 0)}",
            "remaining lots": inventory_age.get("remaining_lots", 0),
            "median lot age s": _fmt_number(
                inventory_age.get("median_wallet_lot_age_seconds"), 0
            ),
            "oldest lot age s": _fmt_number(
                inventory_age.get("oldest_lot_age_seconds"), 0
            ),
            "capital deployed ETH": _fmt_number(
                performance.get("capital_deployed_eth")
            ),
            "profit factor": (
                "∞"
                if distribution.get("profit_factor_unbounded")
                else (
                    f"{distribution['profit_factor']:.2f}x"
                    if distribution.get("profit_factor") is not None
                    else "—"
                )
            ),
            "median net ETH": _fmt_number(distribution.get("median_net_eth")),
            "p10 / p90 net ETH": f"{_fmt_number(distribution.get('p10_net_eth'))} / "
            f"{_fmt_number(distribution.get('p90_net_eth'))}",
            "top10 profit bps": _fmt_number(
                distribution.get("top10_profit_share_bps"), 0
            ),
            "profit HHI bps": _fmt_number(distribution.get("profit_hhi_bps"), 0),
        },
    )
    key = "top_by_roi" if sort == "roi" else "top_by_net"
    rows = (summary.get(key) or [])[:top]
    label = "net ROI" if sort == "roi" else "net quote"
    table = Table(title=f"Top {len(rows)} wallets by {label}")
    table.add_column("Wallet", style="cyan")
    table.add_column("Cohort", justify="center")
    table.add_column("Tokens end", justify="right")
    table.add_column("Realized", justify="right")
    table.add_column("Unrealized", justify="right")
    table.add_column("Gas", justify="right")
    table.add_column("Net", justify="right")
    table.add_column("ROI bps", justify="right")
    table.add_column("Hold s", justify="right")
    for row in rows:
        table.add_row(
            _short_address(row["wallet"]),
            "•" if row.get("cohort") else "",
            _fmt_number(row.get("tokens_end"), 2),
            _fmt_number(row.get("realized_quote_eth")),
            _fmt_number(row.get("unrealized_quote_eth")),
            _fmt_number(row.get("gas_quote_eth")),
            _fmt_net(row.get("net_quote_eth")),
            _fmt_number(row.get("net_roi_bps"), 0),
            _fmt_number(row.get("holding_seconds"), 0),
        )
    console.print(table)

    worst_lots = (summary.get("lot_extremes") or {}).get("worst_unrealized") or []
    if worst_lots:
        table = Table(title="Largest unrealized lot losses")
        table.add_column("Wallet", style="cyan")
        table.add_column("Age s", justify="right")
        table.add_column("Cost ETH", justify="right")
        table.add_column("Mark ETH", justify="right")
        table.add_column("Unrealized ETH", justify="right")
        for row in worst_lots[:5]:
            table.add_row(
                _short_address(row["wallet"]),
                _fmt_number(row.get("age_seconds"), 0),
                _fmt_number(row.get("cost_eth")),
                _fmt_number(row.get("mark_value_eth")),
                _fmt_number(row.get("unrealized_pnl_eth")),
            )
        console.print(table)

    best_lots = (summary.get("lot_extremes") or {}).get("best_unrealized") or []
    if best_lots:
        table = Table(title="Largest unrealized lot gains")
        table.add_column("Wallet", style="cyan")
        table.add_column("Age s", justify="right")
        table.add_column("Cost ETH", justify="right")
        table.add_column("Mark ETH", justify="right")
        table.add_column("Unrealized ETH", justify="right")
        for row in best_lots[:5]:
            table.add_row(
                _short_address(row["wallet"]),
                _fmt_number(row.get("age_seconds"), 0),
                _fmt_number(row.get("cost_eth")),
                _fmt_number(row.get("mark_value_eth")),
                _fmt_number(row.get("unrealized_pnl_eth")),
            )
        console.print(table)

    holdings = summary.get("protocol_holdings") or []
    if holdings:
        table = Table(title="Protocol holdings")
        table.add_column("Role", style="cyan")
        table.add_column("Address")
        table.add_column("Tokens", justify="right")
        for row in holdings:
            table.add_row(
                row["role"],
                _short_address(row["address"]),
                _fmt_number(row.get("tokens"), 2),
            )
        console.print(table)

    if summary.get("cohort"):
        cohort = summary["cohort"]
        console.print(
            f"[dim]Cohort: {cohort.get('wallets', 0)} wallets · "
            f"end {_fmt_number(cohort.get('tokens_end'), 2)} tokens · "
            f"net {_fmt_number(cohort.get('net_quote_eth'))} ETH[/dim]"
        )
    if summary.get("reconciled"):
        console.print("[green]Supply and token inventory reconcile.[/green]")
    else:
        console.print(
            f"[red]Unaccounted tokens: {summary.get('unaccounted', '?')}[/red]"
        )


def _route_performance_tables(summary: dict, top: int, sort: str) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m launch-route performance[/bold]"
        )
    )
    _key_value(
        "Route performance",
        {
            "routes": summary.get("routes", 0),
            "routed wallets": summary.get("wallets", 0),
            "unassigned wallets": summary.get("unassigned_wallets", 0),
            "net ETH": _fmt_number(summary.get("net_quote_eth")),
            "basis ETH": _fmt_number(summary.get("basis_deployed_eth")),
            "realized ETH": _fmt_number(summary.get("realized_quote_eth")),
            "unrealized ETH": _fmt_number(summary.get("unrealized_quote_eth")),
            "gas ETH": _fmt_number(summary.get("gas_quote_eth")),
            "fee wallets": summary.get("fee_wallets", 0),
            "fee ETH": _fmt_number(summary.get("total_fee_eth")),
            "fee burden bps": summary.get("fee_burden_bps"),
            "net ROI bps": summary.get("net_roi_bps"),
            "retained wallets": summary.get("retained_wallets", 0),
            "retention bps": summary.get("retention_bps"),
            "unassigned net ETH": _fmt_number(summary.get("unassigned_net_quote_eth")),
        },
    )
    keys = {
        "net": "top_by_net",
        "roi": "top_by_roi",
        "fees": "top_by_fees",
        "retention": "top_by_retention",
    }
    rows = summary.get(keys[sort]) or []
    rows = rows[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} routes by {sort}")
        table.add_column("Route", style="cyan", no_wrap=True)
        table.add_column("Selector", no_wrap=True)
        table.add_column("Wallets", justify="right")
        table.add_column("Launch ETH", justify="right")
        table.add_column("Net ETH", justify="right")
        if sort == "fees":
            table.add_column("Fee ETH", justify="right")
            table.add_column("Burden bps", justify="right")
        elif sort == "retention":
            table.add_column("Retained", justify="right")
            table.add_column("Ret bps", justify="right")
        else:
            table.add_column("ROI bps", justify="right")
            table.add_column("Win/Loss", justify="right")
        for row in rows:
            values = [
                row.get("route_short") or "",
                row.get("selector") or "",
                str(row.get("wallets", 0)),
                _fmt_number(row.get("launch_buy_volume_eth")),
                _fmt_net(row.get("net_quote_eth")),
            ]
            if sort == "fees":
                values.extend(
                    [
                        _fmt_number(row.get("total_fee_eth")),
                        str(row.get("fee_burden_bps"))
                        if row.get("fee_burden_bps") is not None
                        else "—",
                    ]
                )
            elif sort == "retention":
                values.extend(
                    [
                        str(row.get("retained_wallets", 0)),
                        str(row.get("retention_bps"))
                        if row.get("retention_bps") is not None
                        else "—",
                    ]
                )
            else:
                values.extend(
                    [
                        str(row.get("net_roi_bps"))
                        if row.get("net_roi_bps") is not None
                        else "—",
                        (
                            f"{row.get('profitable_wallets')}/{row.get('losing_wallets')}"
                            if row.get("profitable_wallets") is not None
                            and row.get("losing_wallets") is not None
                            else "—"
                        ),
                    ]
                )
            table.add_row(*values)
        console.print(table)
    console.print(f"[dim]{summary.get('scope', '')}[/dim]")
