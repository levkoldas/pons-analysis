"""Cohort graph, cluster, cluster-quality, and fee renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import _fmt_net, _fmt_number, _key_value, _short_address


def _cohort_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m cohort[/bold]"
        )
    )
    edges = summary.get("edges") or {}
    _key_value(
        "Cohort",
        {
            "roots": summary.get("cohort_wallets", 0),
            "linked wallets": summary.get("linked_wallets", 0),
            "additional": summary.get("additional_wallets", 0),
            "generations": summary.get("generations", 0),
            "links": f"{edges.get('linked', 0)} linked / {edges.get('used', 0)} new",
            "observed edges": f"{edges.get('rotations', 0)} rotations / "
            f"{edges.get('transfers', 0)} transfers",
            "terminal holders": summary.get("terminal_holders", 0),
            "exited wallets": summary.get("exited_wallets", 0),
            "terminal tokens": _fmt_number(summary.get("terminal_tokens"), 2),
            "terminal value ETH": _fmt_number(summary.get("terminal_value_eth")),
            "realized ETH": _fmt_number(summary.get("realized_quote_eth")),
            "unrealized ETH": _fmt_number(summary.get("unrealized_quote_eth")),
            "gas ETH": _fmt_number(summary.get("gas_quote_eth")),
            "net ETH": _fmt_number(summary.get("net_quote_eth")),
            "top holder bps": summary.get("terminal_concentration_bps", 0),
        },
    )

    generations = summary.get("generation_rows") or []
    if generations:
        table = Table(title="Generations")
        table.add_column("Gen", justify="right")
        table.add_column("Wallets", justify="right")
        table.add_column("Terminal", justify="right")
        table.add_column("Tokens end", justify="right")
        table.add_column("Realized", justify="right")
        table.add_column("Unrealized", justify="right")
        table.add_column("Net", justify="right")
        for row in generations:
            table.add_row(
                str(row["generation"]),
                str(row["wallets"]),
                str(row["terminal_holders"]),
                _fmt_number(row.get("tokens_end"), 2),
                _fmt_number(row.get("realized_quote_eth")),
                _fmt_number(row.get("unrealized_quote_eth")),
                _fmt_net(row.get("net_quote_eth")),
            )
        console.print(table)

    holders = (summary.get("top_terminal_holders") or [])[:top]
    if holders:
        table = Table(title=f"Top {len(holders)} terminal holders")
        table.add_column("Wallet", style="cyan")
        table.add_column("Gen", justify="right")
        table.add_column("Relation")
        table.add_column("Tokens", justify="right")
        table.add_column("Unrealized", justify="right")
        table.add_column("Net", justify="right")
        for row in holders:
            table.add_row(
                _short_address(row["wallet"]),
                str(row["generation"]),
                row["relation"],
                _fmt_number(row.get("tokens_end"), 2),
                _fmt_number(row.get("unrealized_quote_eth")),
                _fmt_net(row.get("net_quote_eth")),
            )
        console.print(table)

    if summary.get("reconciled"):
        console.print(
            "[green]Terminal holdings reconcile with linked balances.[/green]"
        )
    else:
        console.print("[red]Terminal holdings do not reconcile.[/red]")


def _clusters_tables(summary: dict, top: int) -> None:
    edges = summary.get("edges") or {}
    behavior = summary.get("behavior") or {}
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m clusters[/bold]"
        )
    )
    _key_value(
        "Evidence",
        {
            "wallets": summary.get("wallets", 0),
            "funding wallets": summary.get("funding_wallets", 0),
            "clusters": summary.get("clusters", 0),
            "clustered wallets": summary.get("clustered_wallets", 0),
            "singletons": summary.get("singleton_wallets", 0),
            "largest cluster": summary.get("largest_cluster", 0),
            "co-trade edges": edges.get("co_trade", 0),
            "timing edges": edges.get("timing", 0),
            "funding edges": edges.get("funding", 0),
            "calldata edges": edges.get("calldata", 0),
            "shared funders": summary.get("shared_funder_groups", 0),
            "calldata groups": summary.get("calldata_groups", 0),
            "min timing": summary.get("min_timing", 0),
            "round trips": behavior.get("round_trips", 0),
            "same-block trips": behavior.get("same_block_round_trips", 0),
            "trip win %": (
                f"{behavior['win_rate'] * 100:.1f}%"
                if behavior.get("win_rate") is not None
                else "—"
            ),
            "median hold s": _fmt_number(behavior.get("median_hold_seconds"), 0),
            "trip PnL ETH": _fmt_number(behavior.get("trade_round_trip_pnl_eth")),
            "unmatched tokens": _fmt_number(behavior.get("unmatched_sell_tokens"), 2),
        },
    )
    if summary.get("method_note"):
        console.print(f"[dim]{summary['method_note']}[/dim]")

    rows = (summary.get("top_clusters") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} clusters")
        table.add_column("Cluster", style="cyan", no_wrap=True)
        table.add_column("Wallets", justify="right", no_wrap=True)
        table.add_column("Tokens end", justify="right", no_wrap=True)
        table.add_column("Realized", justify="right", no_wrap=True)
        table.add_column("Unrealized", justify="right", no_wrap=True)
        table.add_column("Net", justify="right", no_wrap=True)
        for row in rows:
            table.add_row(
                row["cluster_id"].replace("cluster-", "c"),
                str(row["wallets"]),
                _fmt_number(row.get("tokens_end"), 2),
                _fmt_number(row.get("realized_quote_eth")),
                _fmt_number(row.get("unrealized_quote_eth")),
                _fmt_net(row.get("net_quote_eth")),
            )
        console.print(table)

        table = Table(title="Cluster evidence")
        table.add_column("Cluster", style="cyan", no_wrap=True)
        table.add_column("Co-trade", justify="right", no_wrap=True)
        table.add_column("Timing", justify="right", no_wrap=True)
        table.add_column("Funding", justify="right", no_wrap=True)
        table.add_column("Calldata", justify="right", no_wrap=True)
        table.add_column("Shared funders", justify="right", no_wrap=True)
        table.add_column("Fresh", justify="right", no_wrap=True)
        for row in rows:
            table.add_row(
                row["cluster_id"].replace("cluster-", "c"),
                str(row["co_trade_edges"]),
                str(row["timing_edges"]),
                str(row["funding_edges"]),
                str(row["calldata_edges"]),
                str(row["shared_funders"]),
                str(row["fresh_wallets"]),
            )
        console.print(table)

        table = Table(title="Cluster behavior (trade-only FIFO round trips)")
        table.add_column("Cluster", style="cyan", no_wrap=True)
        table.add_column("Round trips", justify="right", no_wrap=True)
        table.add_column("Win %", justify="right", no_wrap=True)
        table.add_column("Same block", justify="right", no_wrap=True)
        table.add_column("Hold s", justify="right", no_wrap=True)
        table.add_column("PnL", justify="right", no_wrap=True)
        for row in rows:
            win_rate = row.get("win_rate")
            table.add_row(
                row["cluster_id"].replace("cluster-", "c"),
                str(row["round_trips"]),
                "—" if win_rate is None else f"{win_rate * 100:.1f}%",
                str(row["same_block_round_trips"]),
                _fmt_number(row.get("median_hold_seconds"), 0),
                _fmt_number(row.get("trade_round_trip_pnl_eth")),
            )
        console.print(table)

    funders = (summary.get("shared_funders") or [])[:top]
    if funders:
        table = Table(title="Shared funders")
        table.add_column("Funder", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Value ETH", justify="right")
        table.add_column("Core", justify="center")
        for row in funders:
            table.add_row(
                _short_address(row["source"]),
                str(len(row.get("members") or [])),
                _fmt_number(row.get("value_eth")),
                "•" if row.get("source_in_core") else "",
            )
        console.print(table)


def _cluster_quality_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m cluster quality[/bold]"
        )
    )
    _key_value(
        "Cluster quality",
        {
            "clusters": summary.get("clusters", 0),
            "clustered wallets": summary.get("wallets", 0),
            "execution wallets": summary.get("execution_wallets", 0),
            "execution volume ETH": _fmt_number(summary.get("execution_volume_eth")),
            "weighted impact bps": _fmt_number(
                summary.get("execution_weighted_bps"), 0
            ),
            "fee wallets": summary.get("fee_wallets", 0),
            "fee volume ETH": _fmt_number(summary.get("fee_volume_eth")),
            "total fee ETH": _fmt_number(summary.get("total_fee_eth")),
            "fee burden bps": _fmt_number(summary.get("fee_burden_bps"), 0),
            "gas ETH": _fmt_number(summary.get("gas_eth")),
            "profitable wallets": summary.get("profitable_wallets", 0),
            "losing wallets": summary.get("losing_wallets", 0),
        },
    )
    rows = sorted(
        (summary.get("rows") or []),
        key=lambda row: (
            -(row.get("execution_weighted_bps") or -1),
            row["cluster_id"],
        ),
    )[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} clusters by execution impact")
        table.add_column("Cluster", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Exec", justify="right")
        table.add_column("Exec ETH", justify="right")
        table.add_column("Impact bps", justify="right")
        table.add_column("Fee ETH", justify="right")
        table.add_column("Burden bps", justify="right")
        table.add_column("Net ETH", justify="right")
        table.add_column("ROI bps", justify="right")
        table.add_column("Fresh", justify="right")
        for row in rows:
            table.add_row(
                row["cluster_id"].replace("cluster-", "c"),
                str(row.get("wallets", 0)),
                str(row.get("execution_wallets", 0)),
                _fmt_number(row.get("execution_volume_eth")),
                _fmt_number(row.get("execution_weighted_bps"), 0),
                _fmt_number(row.get("total_fee_eth")),
                _fmt_number(row.get("fee_burden_bps"), 0),
                _fmt_net(row.get("net_quote_eth")),
                _fmt_number(row.get("net_roi_bps"), 0),
                str(row.get("fresh_wallets", 0)),
            )
        console.print(table)
    console.print(f"[dim]{summary.get('scope', '')}[/dim]")


def _fees_tables(summary: dict, top: int) -> None:
    totals = summary.get("totals") or {}
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m fees[/bold]"
        )
    )
    _key_value(
        "Charged fees",
        {
            "trades": totals.get("trades", 0),
            "gross volume ETH": _fmt_number(totals.get("volume_eth")),
            "quote fee ETH": _fmt_number(totals.get("fee_quote_eth")),
            "creator tax ETH": _fmt_number(totals.get("tax_quote_eth")),
            "token fee value ETH": _fmt_number(totals.get("token_fee_value_eth")),
            "token tax value ETH": _fmt_number(totals.get("token_tax_value_eth")),
            "total fee ETH": _fmt_number(totals.get("total_fee_eth")),
            "burden bps": (
                totals.get("fee_burden_bps")
                if totals.get("fee_burden_bps") is not None
                else "—"
            ),
        },
    )
    if summary.get("fee_scope"):
        console.print(f"[dim]{summary['fee_scope']}[/dim]")
    if summary.get("fee_quote_note"):
        console.print(f"[dim]{summary['fee_quote_note']}[/dim]")
    if summary.get("token_fee_valuation"):
        console.print(f"[dim]{summary['token_fee_valuation']}[/dim]")

    groups = summary.get("groups") or []
    if groups:
        table = Table(title="Fee groups")
        table.add_column("Dimension", style="cyan", no_wrap=True)
        table.add_column("Value")
        table.add_column("Trades", justify="right")
        table.add_column("Gross volume", justify="right")
        table.add_column("Fee ETH", justify="right")
        table.add_column("Burden bps", justify="right")
        for row in groups:
            table.add_row(
                row["dimension"],
                row["value"],
                str(row["trades"]),
                _fmt_number(row.get("volume_eth")),
                _fmt_number(row.get("total_fee_eth")),
                str(row["fee_burden_bps"])
                if row.get("fee_burden_bps") is not None
                else "—",
            )
        console.print(table)

    wallets = (summary.get("top_wallets") or [])[:top]
    if wallets:
        table = Table(title=f"Top {len(wallets)} fee payers")
        table.add_column("Wallet", style="cyan", no_wrap=True)
        table.add_column("Trades", justify="right")
        table.add_column("Gross volume", justify="right")
        table.add_column("Quote fee", justify="right")
        table.add_column("Token fee value", justify="right")
        table.add_column("Total", justify="right")
        table.add_column("Burden bps", justify="right")
        for row in wallets:
            table.add_row(
                _short_address(row["wallet"]),
                str(row["trades"]),
                _fmt_number(row.get("volume_eth")),
                _fmt_number(row.get("fee_quote_eth")),
                _fmt_number(row.get("token_fee_value_eth")),
                _fmt_number(row.get("total_fee_eth")),
                str(row["fee_burden_bps"])
                if row.get("fee_burden_bps") is not None
                else "—",
            )
        console.print(table)
