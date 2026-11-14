"""Wallet scorecard, funding, provenance, and execution renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import _fmt_net, _fmt_number, _key_value, _short_address


def _wallet_scorecard_tables(summary: dict, top: int, sort: str) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m wallets[/bold]"
        )
    )
    _key_value(
        "Wallet scorecard",
        {
            "wallets": summary.get("wallets", 0),
            "profitable / losing": (
                f"{summary.get('profitable_wallets')} / {summary.get('losing_wallets')}"
                if summary.get("profitable_wallets") is not None
                and summary.get("losing_wallets") is not None
                else "—"
            ),
            "net ETH": _fmt_net(summary.get("net_quote_eth")),
            "basis ETH": _fmt_number(summary.get("basis_deployed_eth")),
            "net ROI bps": _fmt_number(summary.get("net_roi_bps"), 0),
            "fee wallets": summary.get("fee_wallets", 0),
            "fee ETH": _fmt_number(summary.get("total_fee_eth")),
            "fee burden bps": _fmt_number(summary.get("fee_burden_bps"), 0),
            "execution wallets": summary.get("execution_wallets", 0),
            "exec weighted bps": _fmt_number(summary.get("execution_weighted_bps"), 0),
            "prefunded / fresh": f"{summary.get('prefunded_wallets', 0)} / "
            f"{summary.get('fresh_wallets', 0)}",
            "route / retention wallets": f"{summary.get('route_wallets', 0)} / "
            f"{summary.get('retention_wallets', 0)}",
        },
    )
    key = {
        "net": "top_by_net",
        "roi": "top_by_roi",
        "impact": "top_by_impact",
        "fees": "top_by_fees",
        "retention": "top_by_retention",
    }[sort]
    rows = (summary.get(key) or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} wallets by {sort}")
        table.add_column("Wallet", style="cyan")
        table.add_column("Entry")
        table.add_column("Net ETH", justify="right")
        table.add_column("ROI bps", justify="right")
        table.add_column("Fee ETH", justify="right")
        if sort == "retention":
            table.add_column("Ret bps", justify="right")
            for row in rows:
                table.add_row(
                    _short_address(row["wallet"]),
                    row.get("entry_phase", ""),
                    _fmt_net(row.get("net_quote_eth")),
                    _fmt_number(row.get("net_roi_bps"), 0),
                    _fmt_number(row.get("total_fee_eth")),
                    _fmt_number(row.get("token_retention_bps"), 0),
                )
        else:
            table.add_column("Cluster")
            table.add_column("Fee bps", justify="right")
            table.add_column("Impact bps", justify="right")
            table.add_column("Prefunded", justify="center")
            for row in rows:
                table.add_row(
                    _short_address(row["wallet"]),
                    row.get("entry_phase", ""),
                    _fmt_net(row.get("net_quote_eth")),
                    _fmt_number(row.get("net_roi_bps"), 0),
                    _fmt_number(row.get("total_fee_eth")),
                    row.get("cluster_id", ""),
                    _fmt_number(row.get("fee_burden_bps"), 0),
                    _fmt_number(row.get("execution_weighted_bps"), 0),
                    "•" if row.get("prefunded") is True else "",
                )
        console.print(table)


def _funding_tables(summary: dict) -> None:
    flow = summary.get("flow") or {}
    console.print(
        Panel(f"[bold]{summary.get('profile', '')} · native funding graph[/bold]")
    )
    _key_value(
        "Flow",
        {
            "wallets": summary.get("wallets", 0),
            "transactions": summary.get("transactions", 0),
            "internal transfers": summary.get("internal_transfers", 0),
            "edges": summary.get("edges", 0),
            "inflow ETH": _fmt_number(flow.get("inflow_eth")),
            "outflow ETH": _fmt_number(flow.get("outflow_eth")),
            "gas ETH": _fmt_number(flow.get("gas_eth")),
            "net ETH": _fmt_number(flow.get("net_flow_eth")),
            "residual ETH": _fmt_number(flow.get("residual_eth")),
            "members internal": _fmt_number(flow.get("internal_eth")),
        },
    )

    funders = (summary.get("counterparties") or {}).get("funders") or []
    if funders:
        table = Table(title="Top external funders")
        table.add_column("Funder", style="cyan")
        table.add_column("Value ETH", justify="right")
        table.add_column("Edges", justify="right")
        for row in funders:
            table.add_row(
                _short_address(row["address"]),
                _fmt_number(row.get("value_eth")),
                str(row.get("edges", "")),
            )
        console.print(table)

    hubs = summary.get("fanout_hubs") or []
    if hubs:
        table = Table(title="Fan-out hubs")
        table.add_column("Source", style="cyan")
        table.add_column("Core", justify="center")
        table.add_column("Recipients", justify="right")
        table.add_column("Value ETH", justify="right")
        table.add_column("Methods")
        for row in hubs:
            methods = ", ".join(
                f"{name}:{count}" for name, count in row["methods"].items()
            )
            table.add_row(
                _short_address(row["source"]),
                "•" if row.get("source_in_core") else "",
                str(row.get("recipients", "")),
                _fmt_number(row.get("value_eth")),
                methods,
            )
        console.print(table)

    fresh = summary.get("fresh_wallets") or []
    if fresh:
        table = Table(title="Fresh wallets")
        table.add_column("Wallet", style="cyan")
        table.add_column("Nonce", justify="right")
        table.add_column("Balance ETH", justify="right")
        table.add_column("Inbound ETH", justify="right")
        table.add_column("Transactions", justify="right")
        table.add_column("Contract", justify="center")
        for row in fresh:
            table.add_row(
                _short_address(row["wallet"]),
                str(row.get("nonce", "")),
                _fmt_number(row.get("balance_eth")),
                _fmt_number(row.get("inbound_eth")),
                str(row.get("transactions", "")),
                "•" if row.get("is_contract") else "",
            )
        console.print(table)

    if flow.get("reconciled"):
        console.print("[green]Native flow and current balances reconcile.[/green]")
    else:
        console.print(
            f"[yellow]Flow residual: {_fmt_number(flow.get('residual_eth'))} ETH"
            "[/yellow]"
        )


def _provenance_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m provenance[/bold]"
        )
    )
    _key_value(
        "Funding timing",
        {
            "wallets": summary.get("wallets", 0),
            "prefunded": f"{summary.get('prefunded_wallets', 0)} "
            f"({_fmt_number(summary.get('prefunded_bps'), 0)} bps)",
            "post-funded": summary.get("postfunded_wallets", 0),
            "unknown timing": summary.get("unknown_timing", 0),
            "median lead s": _fmt_number(summary.get("median_prefund_lead_seconds"), 0),
            "max lead s": _fmt_number(summary.get("max_prefund_lead_seconds"), 0),
            "prefund value ETH": _fmt_number(summary.get("total_prefund_value_eth")),
            "fresh / prefunded": f"{summary.get('fresh_wallets', 0)} / "
            f"{summary.get('fresh_prefunded', 0)}",
        },
    )
    rows = (summary.get("rows") or [])[:top]
    if rows:
        table = Table(title=f"Wallet funding provenance ({len(rows)})")
        table.add_column("Wallet", style="cyan")
        table.add_column("Cluster")
        table.add_column("Fresh", justify="center")
        table.add_column("Entry")
        table.add_column("Lead s", justify="right")
        table.add_column("Source")
        table.add_column("Value ETH", justify="right")
        table.add_column("Net ETH", justify="right")
        for row in rows:
            table.add_row(
                _short_address(row["wallet"]),
                row.get("cluster_id", ""),
                "•" if row.get("fresh") else "",
                row.get("entry_phase", ""),
                _fmt_number(row.get("lead_seconds"), 0),
                _short_address(row.get("first_inflow_source", ""))
                if row.get("first_inflow_source")
                else "",
                _fmt_number(row.get("first_inflow_value_eth")),
                _fmt_net(row.get("net_quote_eth")),
            )
        console.print(table)
    sources = summary.get("top_sources") or []
    if sources:
        table = Table(title="Top prefunding sources")
        table.add_column("Source", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Value ETH", justify="right")
        for row in sources[:top]:
            table.add_row(
                _short_address(row["source"]),
                str(row.get("wallets", 0)),
                _fmt_number(row.get("value_eth")),
            )
        console.print(table)
    console.print(f"[dim]{summary.get('scope', '')}[/dim]")


def _execution_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m execution[/bold]"
        )
    )
    _key_value(
        "Attribution",
        {
            "wallets": summary.get("wallets", 0),
            "v4 impact trades": summary.get("impact_trades", 0),
            "attributed": f"{summary.get('attributed_trades', 0)} / "
            f"{summary.get('impact_trades', 0)} "
            f"({_fmt_number(summary.get('coverage_bps'), 0)} bps coverage)",
            "unattributed": summary.get("unattributed_trades", 0),
            "volume ETH": _fmt_number(summary.get("volume_eth")),
            "median abs bps": _fmt_number(summary.get("median_abs_bps"), 0),
            "p90 abs bps": _fmt_number(summary.get("p90_abs_bps"), 0),
            "max abs bps": _fmt_number(summary.get("max_abs_bps"), 0),
            "volume-weighted bps": _fmt_number(
                summary.get("volume_weighted_abs_bps"), 0
            ),
        },
    )
    groups = summary.get("groups") or []
    if groups:
        table = Table(title="Impact groups")
        table.add_column("Dimension", style="cyan")
        table.add_column("Value")
        table.add_column("Trades", justify="right")
        table.add_column("Volume ETH", justify="right")
        table.add_column("Median abs bps", justify="right")
        table.add_column("P90 abs bps", justify="right")
        table.add_column("Max abs bps", justify="right")
        table.add_column("Vol-weighted bps", justify="right")
        for row in groups:
            table.add_row(
                row["dimension"],
                row["value"],
                str(row.get("trades", 0)),
                _fmt_number(row.get("volume_eth")),
                _fmt_number(row.get("median_abs_bps"), 0),
                _fmt_number(row.get("p90_abs_bps"), 0),
                _fmt_number(row.get("max_abs_bps"), 0),
                _fmt_number(row.get("volume_weighted_abs_bps"), 0),
            )
        console.print(table)

    rows = (summary.get("top_by_weighted") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} wallets by volume-weighted impact")
        table.add_column("Wallet", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Buy / Sell", justify="right")
        table.add_column("Volume ETH", justify="right")
        table.add_column("Median abs bps", justify="right")
        table.add_column("P90 abs bps", justify="right")
        table.add_column("Max abs bps", justify="right")
        table.add_column("Vol-weighted bps", justify="right")
        for row in rows:
            table.add_row(
                _short_address(row["wallet"]),
                str(row.get("trades", 0)),
                f"{row.get('buy_trades', 0)} / {row.get('sell_trades', 0)}",
                _fmt_number(row.get("volume_eth")),
                _fmt_number(row.get("median_abs_bps"), 0),
                _fmt_number(row.get("p90_abs_bps"), 0),
                _fmt_number(row.get("max_abs_bps"), 0),
                _fmt_number(row.get("volume_weighted_abs_bps"), 0),
            )
        console.print(table)
    console.print(f"[dim]{summary.get('scope', '')}[/dim]")
