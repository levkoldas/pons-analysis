"""Evidence collection commands."""

import typer

from ..renderers.common import _key_value
from ..runtime import collect_app, console


@collect_app.command("launch")
def collect_launch(
    ctx: typer.Context,
    head: int | None = typer.Option(
        None, help="Coverage head block; defaults to the chain head."
    ),
):
    """Collect launch and curve evidence."""
    case = ctx.obj
    with console.status("[bold cyan]Collecting launch evidence..."):
        result = case.collect_launch(head=head)
    _key_value("Launch snapshot", result)


@collect_app.command("window")
def collect_window(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    prior: int | None = typer.Option(None, help="Extend this existing window."),
    activity: bool = typer.Option(False, help="Fetch GMGN activity for participants."),
    head: int | None = typer.Option(None, help="Upper block bound."),
):
    """Collect a bounded analysis window."""
    case = ctx.obj
    with console.status(f"[bold cyan]Collecting {minutes}m window..."):
        result = case.collect_window(
            minutes, prior_minutes=prior, with_activity=activity, head=head
        )
    _key_value(f"{minutes}m window", result)


@collect_app.command("successors")
def collect_successor_evidence(
    ctx: typer.Context,
    wallet: list[str] = typer.Option(..., "-w", "--wallet", help="Root wallet."),
    start_block: int | None = typer.Option(None),
    activity: bool = typer.Option(True, "--activity/--no-activity"),
):
    """Collect descendants of one or more root wallets."""
    case = ctx.obj
    with console.status("[bold cyan]Walking the transfer graph..."):
        result = case.collect_successors(
            wallet, start_block=start_block, with_activity=activity
        )
    _key_value("Successor snapshot", result)


@collect_app.command("funding")
def collect_funding_cmd(
    ctx: typer.Context,
    wallet: list[str] = typer.Option(..., "-w", "--wallet", help="Wallet to include."),
    start_block: int | None = typer.Option(None, help="Drop history below this block."),
    cap: int = typer.Option(
        100, min=1, help="Maximum Blockscout pages per wallet and history."
    ),
):
    """Collect native transaction and internal-transfer histories."""
    case = ctx.obj
    with console.status("[bold cyan]Collecting funding histories..."):
        result = case.collect_funding(wallet, start_block=start_block, cap=cap)
    _key_value("Funding snapshot", result)
