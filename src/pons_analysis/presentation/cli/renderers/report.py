"""Rendered report overview."""

from rich.panel import Panel

from ..runtime import console
from .common import _fmt_number, _key_value


def _report_tables(data: dict) -> None:
    profile = data.get("profile") or {}
    positions = (data.get("positions") or {}).get("summary") or {}
    trajectory = (data.get("trajectory") or {}).get("summary") or {}
    cohort = data.get("cohort") or {}
    funding = data.get("funding") or {}
    clusters = data.get("clusters") or {}
    behavior = clusters.get("behavior") or {}
    fees = data.get("fees") or {}
    fee_totals = fees.get("totals") or {}
    replay = trajectory.get("reserve_replay") or {}
    console.print(
        Panel(
            f"[bold]{profile.get('name', '')} · "
            f"{data.get('minutes', '')}m report[/bold]"
        )
    )
    _key_value(
        "Output",
        {
            "html": data["artifacts"]["html"],
            "json": data["artifacts"]["json"],
            "sources": len(data.get("sources") or {}),
        },
    )
    _key_value(
        "Highlights",
        {
            "volume ETH": _fmt_number(trajectory.get("volume_eth")),
            "net PnL ETH": _fmt_number(
                (positions.get("totals") or {}).get("net_quote_eth")
            ),
            "wallet ROI bps": _fmt_number(
                (positions.get("performance") or {}).get("net_roi_bps"), 0
            ),
            "median hold s": _fmt_number(
                (positions.get("performance") or {}).get("median_holding_seconds"), 0
            ),
            "terminal holders": (
                cohort.get("terminal_holders")
                if cohort.get("terminal_holders") is not None
                else "—"
            ),
            "terminal value ETH": _fmt_number(cohort.get("terminal_value_eth"))
            if cohort
            else "—",
            "reserve replay": (
                "reconciled"
                if replay.get("reconciled") is True
                else "not reconciled"
                if replay.get("reconciled") is False
                else "n/a"
            ),
            "funding residual ETH": _fmt_number(
                (funding.get("flow") or {}).get("residual_eth")
            )
            if funding
            else "—",
            "clusters": (
                clusters.get("clusters")
                if clusters and clusters.get("clusters") is not None
                else "—"
            ),
            "round trips": (
                behavior.get("round_trips")
                if clusters and behavior.get("round_trips") is not None
                else "—"
            ),
            "fees ETH": _fmt_number(fee_totals.get("total_fee_eth")) if fees else "—",
            "fee burden bps": (
                fee_totals.get("fee_burden_bps")
                if fees and fee_totals.get("fee_burden_bps") is not None
                else "—"
            ),
        },
    )
    console.print(
        f"[green]Wrote[/green] {data['artifacts']['html']} and "
        f"{data['artifacts']['json']}"
    )
