"""Summary and window-comparison renderers."""

from rich.panel import Panel
from rich.table import Table

from ..runtime import console
from .common import _fmt_metric, _fmt_net, _fmt_number, _key_value


def _summary_tables(summary: dict):
    console.print(Panel(f"[bold]{summary.get('profile', '')}[/bold]", title="Summary"))
    scalar = {
        key: value
        for key, value in summary.items()
        if not isinstance(value, (dict, list))
    }
    _key_value("Metrics", scalar)
    for key in ("all", "user", "protocol", "curve", "v4", "groups", "top_routes"):
        value = summary.get(key)
        if isinstance(value, dict):
            _key_value(key, value)
        elif isinstance(value, list):
            table = Table(title=key)
            columns = sorted({column for row in value for column in row})
            for column in columns:
                table.add_column(str(column))
            for row in value:
                table.add_row(*(str(row.get(column, "")) for column in columns))
            console.print(table)


def _comparison_tables(summary: dict) -> None:
    console.print(
        Panel(
            f"[bold]{summary.get('profile', '')} · "
            f"{summary['left_minutes']}m → {summary['right_minutes']}m comparison[/bold]"
        )
    )
    rows = summary.get("metrics") or []
    if rows:
        table = Table(title="Window deltas")
        table.add_column("Metric", no_wrap=True)
        for column in ("Left", "Right", "Delta", "Delta %"):
            table.add_column(column, justify="right", no_wrap=True)
        for row in rows:
            delta_pct = row.get("delta_pct")
            table.add_row(
                f"{row['group']} · {row['metric']}",
                _fmt_metric(row.get("left")),
                _fmt_metric(row.get("right")),
                _fmt_metric(row.get("delta")),
                "—" if delta_pct is None else f"{delta_pct:,.2f}%",
            )
        console.print(table)
    overlap = summary.get("wallet_overlap") or {}
    _key_value(
        "Wallet overlap",
        {
            "left wallets": overlap.get("left_wallets", 0),
            "right wallets": overlap.get("right_wallets", 0),
            "common wallets": overlap.get("overlap_wallets", 0),
            "overlap bps": overlap.get("overlap_bps"),
            "left-only wallets": overlap.get("left_only_wallets", 0),
            "right-only wallets": overlap.get("right_only_wallets", 0),
            "common net left ETH": _fmt_number(overlap.get("overlap_net_left_eth")),
            "common net right ETH": _fmt_number(overlap.get("overlap_net_right_eth")),
            "common net delta ETH": _fmt_net(overlap.get("overlap_net_delta_eth")),
        },
    )
