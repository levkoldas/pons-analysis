"""Formatting and table helpers shared by the CLI renderers."""

import json

from rich.table import Table

from ..runtime import console


def _key_value(title: str, payload: dict):
    table = Table(title=title, show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        elif value is None:
            value = "—"
        table.add_row(str(key), str(value))
    console.print(table)


def _short_address(value: str) -> str:
    return value if len(value) <= 14 else f"{value[:8]}…{value[-4:]}"


def _fmt_number(value: float | None, digits: int = 6) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _fmt_metric(value: int | float | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.4f}"


def _fmt_net(value: float | None) -> str:
    if value is None:
        return "—"
    if value > 0:
        return f"[green]{value:,.6f}[/green]"
    if value < 0:
        return f"[red]{value:,.6f}[/red]"
    return "0.000000"


def _fmt_price(value: float | None) -> str:
    return "—" if value is None else f"{value:.4e}"


def _sparkline(values: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return blocks[3] * len(values)
    return "".join(
        blocks[round((value - low) / (high - low) * (len(blocks) - 1))]
        for value in values
    )
