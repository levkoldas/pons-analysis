"""Entry-cohort, retention, and lifecycle renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import _fmt_net, _fmt_number, _key_value


def _entry_cohort_tables(summary: dict, top: int, sort: str) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m entry cohorts[/bold]"
        )
    )
    _key_value(
        "Entry cohorts",
        {
            "bucket s": summary.get("bucket_seconds", 0),
            "wallets": summary.get("wallets", 0),
            "unbucketable": summary.get("unbucketable_wallets", 0),
            "cohorts": summary.get("cohorts", 0),
            "first entry": str(summary.get("first_entry_utc", ""))[11:19],
            "last entry": str(summary.get("last_entry_utc", ""))[11:19],
            "largest cohort": summary.get("largest_cohort", 0),
        },
    )
    key = {
        "net": "top_by_net",
        "roi": "top_by_roi",
        "wallets": "top_by_wallets",
    }[sort]
    rows = (summary.get(key) or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} cohorts by {sort}")
        table.add_column("Entry", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Open / closed", justify="right")
        table.add_column("Net ETH", justify="right")
        table.add_column("ROI bps", justify="right")
        table.add_column("Median hold s", justify="right")
        table.add_column("C / V4 / T", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("start_utc", ""))[11:19],
                str(row.get("wallets", 0)),
                f"{row.get('open_wallets', 0)} / {row.get('closed_wallets', 0)}",
                _fmt_net(row.get("net_quote_eth")),
                _fmt_number(row.get("roi_bps"), 0),
                _fmt_number(row.get("median_holding_seconds"), 0),
                f"{row.get('curve_wallets', 0)} / {row.get('v4_wallets', 0)} / "
                f"{row.get('transfer_wallets', 0)}",
            )
        console.print(table)


def _retention_tables(summary: dict, top: int) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m retention[/bold]"
        )
    )
    _key_value(
        "Cohort retention",
        {
            "bucket s": summary.get("bucket_seconds", 0),
            "cohorts": summary.get("cohorts", 0),
            "wallets": summary.get("wallets", 0),
            "wallets remaining": summary.get("wallets_remaining", 0),
            "initial tokens": _fmt_number(summary.get("initial_tokens"), 2),
            "remaining tokens": _fmt_number(summary.get("tokens_remaining"), 2),
            "token retention bps": _fmt_number(summary.get("token_retention_bps"), 0),
            "holder retention bps": _fmt_number(summary.get("holder_retention_bps"), 0),
        },
    )
    rows = (summary.get("top_by_retention") or [])[:top]
    if rows:
        table = Table(title=f"Top {len(rows)} cohorts by token retention")
        table.add_column("Entry", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Holders left", justify="right")
        table.add_column("Initial tokens", justify="right")
        table.add_column("Remaining tokens", justify="right")
        table.add_column("Token retention bps", justify="right")
        table.add_column("Holder retention bps", justify="right")
        for row in rows:
            table.add_row(
                str(row.get("entry_utc", ""))[11:19],
                str(row.get("wallets", 0)),
                str(row.get("wallets_remaining", 0)),
                _fmt_number(row.get("initial_tokens"), 2),
                _fmt_number(row.get("tokens_remaining"), 2),
                _fmt_number(row.get("token_retention_bps"), 0),
                _fmt_number(row.get("holder_retention_bps"), 0),
            )
        console.print(table)


def _lifecycle_tables(summary: dict) -> None:
    totals = summary.get("totals") or {}
    phases = summary.get("phases") or []
    groups = summary.get("groups") or []
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary.get('minutes', '')}m lifecycle[/bold]"
        )
    )
    _key_value(
        "Lifecycle",
        {
            "wallets": summary.get("wallets", 0),
            "entry": summary.get("entry_scope", ""),
            "capital deployed ETH": _fmt_number(totals.get("capital_deployed_eth")),
            "net ETH": _fmt_number(totals.get("net_quote_eth")),
            "net ROI bps": _fmt_number(totals.get("net_roi_bps"), 0),
            "open / closed": f"{totals.get('open_wallets', 0)} / "
            f"{totals.get('closed_wallets', 0)}",
            "median hold s": _fmt_number(totals.get("median_holding_seconds"), 0),
        },
    )
    if phases:
        table = Table(title="Entry phases")
        table.add_column("Phase", style="cyan")
        table.add_column("Wallets", justify="right")
        table.add_column("Open", justify="right")
        table.add_column("Closed", justify="right")
        table.add_column("Tokens end", justify="right")
        table.add_column("Capital ETH", justify="right")
        table.add_column("Net ETH", justify="right")
        table.add_column("ROI bps", justify="right")
        table.add_column("Median hold s", justify="right")
        for row in phases:
            table.add_row(
                row["entry_phase"],
                str(row["wallets"]),
                str(row["open_wallets"]),
                str(row["closed_wallets"]),
                _fmt_number(row.get("tokens_end"), 2),
                _fmt_number(row.get("capital_deployed_eth")),
                _fmt_number(row.get("net_quote_eth")),
                _fmt_number(row.get("net_roi_bps"), 0),
                _fmt_number(row.get("median_holding_seconds"), 0),
            )
        console.print(table)
    if groups:
        table = Table(title="Entry phase and exit status")
        table.add_column("Phase", style="cyan")
        table.add_column("Status")
        table.add_column("Wallets", justify="right")
        table.add_column("Capital ETH", justify="right")
        table.add_column("Net ETH", justify="right")
        table.add_column("ROI bps", justify="right")
        table.add_column("Median hold s", justify="right")
        for row in groups:
            table.add_row(
                row["entry_phase"],
                row["status"],
                str(row["wallets"]),
                _fmt_number(row.get("capital_deployed_eth")),
                _fmt_number(row.get("net_quote_eth")),
                _fmt_number(row.get("net_roi_bps"), 0),
                _fmt_number(row.get("median_holding_seconds"), 0),
            )
        console.print(table)
    console.print(f"[dim]{summary.get('roi_scope', '')}[/dim]")
