"""Analysis commands for derived workspace artifacts."""

from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from ..renderers.activity import (
    _entry_cohort_tables,
    _lifecycle_tables,
    _retention_tables,
)
from ..renderers.cohorts import (
    _cluster_quality_tables,
    _clusters_tables,
    _cohort_tables,
    _fees_tables,
)
from ..renderers.market import (
    _candles_tables,
    _flow_tables,
    _holders_tables,
    _trajectory_tables,
)
from ..renderers.positions import _positions_tables, _route_performance_tables
from ..renderers.summary import _summary_tables
from ..renderers.wallets import (
    _execution_tables,
    _funding_tables,
    _provenance_tables,
    _wallet_scorecard_tables,
)
from ..runtime import _print_json, analyze_app, console
from .helpers import _cohort_roots, _read_json


@analyze_app.command("launch")
def analyze_launch(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")):
    """Recompute launch trades, wallets, and holders."""
    case = ctx.obj
    with console.status("[bold cyan]Recomputing launch analysis..."):
        summary = case.analyze_launch()
    if as_json:
        _print_json(summary)
    else:
        _summary_tables(summary)


@analyze_app.command("all")
def refresh_all_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    cohort: list[str] = typer.Option([], "--cohort", help="Cohort wallet to mark."),
    cohort_file: Path | None = typer.Option(
        None, help="JSON list or CSV with a destination_wallet column."
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Run every available analysis and validate the resulting artifacts."""
    case = ctx.obj
    roots = _cohort_roots(case, cohort, cohort_file)
    with console.status("[bold cyan]Refreshing the full analysis graph..."):
        results = case.refresh(minutes, cohort=roots)
    if as_json:
        _print_json(results)
        return
    table = Table(title=f"{minutes}m full refresh")
    table.add_column("Analysis", style="cyan")
    table.add_column("Result")
    for name, value in results.items():
        if name in {"validation", "derived_validation"}:
            status = "[green]pass[/green]" if value.get("passed") else "[red]fail[/red]"
            table.add_row(name.replace("_", " "), status)
        else:
            table.add_row(name.replace("_", " "), "ok")
    console.print(table)
    if not results["validation"].get("passed"):
        raise typer.Exit(1)
    if not results["derived_validation"].get("passed"):
        raise typer.Exit(1)


@analyze_app.command("positions")
def analyze_positions_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    cohort: list[str] = typer.Option([], "--cohort", help="Cohort wallet to mark."),
    cohort_file: Path | None = typer.Option(
        None, help="JSON list or CSV with a destination_wallet column."
    ),
    top: int = typer.Option(15, min=1, max=200, help="Rows to display."),
    sort: str = typer.Option("net", help="Rank wallets by net or roi."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Replay exact token inventory and FIFO quote PnL per wallet."""
    case = ctx.obj
    sort = sort.lower()
    if sort not in {"net", "roi"}:
        raise typer.BadParameter("--sort must be net or roi")
    roots = _cohort_roots(case, cohort, cohort_file)
    with console.status("[bold cyan]Replaying wallet positions..."):
        summary = case.analyze_positions(minutes, cohort=roots)
    if as_json:
        _print_json(summary)
    else:
        _positions_tables(summary, top, sort)


@analyze_app.command("route-performance")
def analyze_route_performance_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(15, min=1, max=100, help="Routes to display."),
    sort: str = typer.Option(
        "net", help="Rank routes by net, roi, fees, or retention."
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Join wallet PnL to the route of each wallet's first launch buy."""
    case = ctx.obj
    sort = sort.lower()
    if sort not in {"net", "roi", "fees", "retention"}:
        raise typer.BadParameter("--sort must be net, roi, fees, or retention")
    with console.status("[bold cyan]Joining launch routes to wallet PnL..."):
        summary = case.analyze_route_performance(minutes)
    if as_json:
        _print_json(summary)
    else:
        _route_performance_tables(summary, top, sort)


@analyze_app.command("entry-cohorts")
def analyze_entry_cohorts_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    bucket: int = typer.Option(60, min=1, help="Entry bucket size in seconds."),
    sort: str = typer.Option("net", help="Rank cohorts by net, roi, or wallets."),
    top: int = typer.Option(15, min=1, max=100, help="Cohorts to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Group wallets by first-activity bucket and aggregate exact performance."""
    case = ctx.obj
    sort = sort.lower()
    if sort not in {"net", "roi", "wallets"}:
        raise typer.BadParameter("--sort must be net, roi, or wallets")
    with console.status("[bold cyan]Aggregating entry-time cohorts..."):
        summary = case.analyze_entry_cohorts(minutes, bucket=bucket)
    if as_json:
        _print_json(summary)
    else:
        _entry_cohort_tables(summary, top, sort)


@analyze_app.command("retention")
def analyze_retention_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    bucket: int = typer.Option(60, min=1, help="Retention bucket size in seconds."),
    top: int = typer.Option(15, min=1, max=100, help="Cohorts to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Measure token and holder retention for entry-time cohorts."""
    case = ctx.obj
    with console.status("[bold cyan]Replaying cohort retention..."):
        summary = case.analyze_retention(minutes, bucket=bucket)
    if as_json:
        _print_json(summary)
    else:
        _retention_tables(summary, top)


@analyze_app.command("lifecycle")
def analyze_lifecycle_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    as_json: bool = typer.Option(False, "--json"),
):
    """Group wallets by first entry phase and open or closed status."""
    case = ctx.obj
    with console.status("[bold cyan]Aggregating wallet lifecycle..."):
        summary = case.analyze_lifecycle(minutes)
    if as_json:
        _print_json(summary)
    else:
        _lifecycle_tables(summary)


@analyze_app.command("trajectory")
def analyze_trajectory_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(10, min=1, max=20, help="Trades to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Replay price, volume, and v4 virtual reserves over a window."""
    case = ctx.obj
    with console.status("[bold cyan]Replaying the trade trajectory..."):
        summary = case.analyze_trajectory(minutes)
    if as_json:
        _print_json(summary)
    else:
        _trajectory_tables(summary, top)


@analyze_app.command("candles")
def analyze_candles_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    bucket: int = typer.Option(60, min=1, help="Bucket size in seconds."),
    top: int = typer.Option(10, min=1, max=50, help="Buckets to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Aggregate trajectory prices into OHLCV candles and a volume profile."""
    case = ctx.obj
    with console.status("[bold cyan]Aggregating OHLCV candles..."):
        summary = case.analyze_candles(minutes, bucket=bucket)
    if as_json:
        _print_json(summary)
    else:
        _candles_tables(summary, top)


@analyze_app.command("holders")
def analyze_holders_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    bucket: int = typer.Option(60, min=1, help="Bucket size in seconds."),
    top: int = typer.Option(10, min=1, max=50, help="Peak snapshots to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Replay holder count, concentration, and HHI over time."""
    case = ctx.obj
    with console.status("[bold cyan]Replaying holder concentration..."):
        summary = case.analyze_holders(minutes, bucket=bucket)
    if as_json:
        _print_json(summary)
    else:
        _holders_tables(summary, top)


@analyze_app.command("flow")
def analyze_flow_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    bucket: int = typer.Option(60, min=1, help="Bucket size in seconds."),
    top: int = typer.Option(10, min=1, max=50, help="Rows to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Aggregate buy/sell order flow and wallet net flow."""
    case = ctx.obj
    with console.status("[bold cyan]Aggregating order flow..."):
        summary = case.analyze_flow(minutes, bucket=bucket)
    if as_json:
        _print_json(summary)
    else:
        _flow_tables(summary, top)


@analyze_app.command("execution")
def analyze_execution_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(15, min=1, max=200, help="Wallets to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Attribute v4 execution impact to economic token wallets."""
    case = ctx.obj
    with console.status("[bold cyan]Joining impact to wallet trade legs..."):
        summary = case.analyze_execution(minutes)
    if as_json:
        _print_json(summary)
    else:
        _execution_tables(summary, top)


@analyze_app.command("cohort")
def analyze_cohort_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    cohort: list[str] = typer.Option([], "--cohort", help="Original cohort wallet."),
    cohort_file: Path | None = typer.Option(
        None, help="JSON list or CSV with a destination_wallet column."
    ),
    top: int = typer.Option(20, min=1, max=200, help="Holders to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Build launch-to-exit generations, terminal holders, and PnL."""
    case = ctx.obj
    roots = _cohort_roots(case, cohort, cohort_file)
    if not roots:
        console.print(
            Panel(
                "Provide at least one --cohort or --cohort-file wallet.",
                title="Cohort error",
                style="red",
            )
        )
        raise typer.Exit(1)
    with console.status("[bold cyan]Building the cohort generation graph..."):
        summary = case.analyze_cohort(minutes, cohort=roots)
    if as_json:
        _print_json(summary)
    else:
        _cohort_tables(summary, top)


@analyze_app.command("clusters")
def analyze_clusters_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    fresh_nonce: int = typer.Option(
        10, min=0, help="Maximum current nonce for a fresh wallet."
    ),
    min_timing: int = typer.Option(
        3, min=2, help="Repeated same-block co-occurrences for a timing link."
    ),
    top: int = typer.Option(10, min=1, max=100, help="Clusters to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Group wallets by co-trades, timing, funding links, funders, and calldata."""
    case = ctx.obj
    with console.status("[bold cyan]Connecting cluster evidence..."):
        summary = case.analyze_clusters(
            minutes, fresh_nonce=fresh_nonce, min_timing=min_timing
        )
    if as_json:
        _print_json(summary)
    else:
        _clusters_tables(summary, top)


@analyze_app.command("cluster-quality")
def analyze_cluster_quality_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(15, min=1, max=100, help="Clusters to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Join clusters to execution impact, fee burden, and lifecycle ROI."""
    case = ctx.obj
    with console.status("[bold cyan]Joining cluster quality artifacts..."):
        summary = case.analyze_cluster_quality(minutes)
    if as_json:
        _print_json(summary)
    else:
        _cluster_quality_tables(summary, top)


@analyze_app.command("fees")
def analyze_fees_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(10, min=1, max=100, help="Fee payers to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Attribute charged fees and taxes by phase, side, and wallet."""
    case = ctx.obj
    with console.status("[bold cyan]Attributing fees and taxes..."):
        summary = case.analyze_fees(minutes)
    if as_json:
        _print_json(summary)
    else:
        _fees_tables(summary, top)


@analyze_app.command("window")
def analyze_window_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    cohort: list[str] = typer.Option([], "--cohort", help="Original cohort wallet."),
    cohort_file: Path | None = typer.Option(
        None, help="JSON list or CSV with a destination_wallet column."
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Recompute an analysis window."""
    case = ctx.obj
    roots = _cohort_roots(case, cohort, cohort_file)
    with console.status("[bold cyan]Recomputing window analysis..."):
        summary = case.analyze_window(minutes, cohort=roots)
    if as_json:
        _print_json(summary)
    else:
        _summary_tables(summary)


@analyze_app.command("ethflow")
def analyze_ethflow(
    ctx: typer.Context,
    address: str = typer.Argument(...),
    transactions: Path = typer.Option(
        Path("evidence/ethflow/transactions.json"), help="Blockscout transaction rows."
    ),
    internal: Path = typer.Option(
        Path("evidence/ethflow/internal_transfers.json"),
        help="Blockscout internal-transfer rows.",
    ),
    balances: Path | None = typer.Option(
        None, help="JSON mapping address to current wei balance."
    ),
):
    """Reconstruct a native-ETH balance sheet and flow statement."""
    case = ctx.obj
    rows = _read_json(case, transactions) or []
    internals = _read_json(case, internal) or []
    current = _read_json(case, balances) if balances else None
    from pons_analysis.analytics.common.ethflow import (
        flow_statement,
        wallet_balance_sheet,
    )

    sheet = wallet_balance_sheet(rows, internals, address)
    statement = flow_statement(
        rows,
        internals,
        members=[address],
        balances={address: int(current[address])}
        if current and address in current
        else None,
    )
    table = Table(title=f"ETH flow · {address}")
    table.add_column("Metric", style="cyan")
    table.add_column("Wei", justify="right")
    for key in ("ext_in", "int_in", "ext_out", "int_out", "gas", "net"):
        table.add_row(key, str(sheet[key]))
    console.print(table)
    _print_json(statement)


@analyze_app.command("funding")
def analyze_funding_cmd(
    ctx: typer.Context,
    fresh_nonce: int = typer.Option(
        10, min=0, help="Maximum current nonce for a fresh wallet."
    ),
    hub_min: int = typer.Option(
        3, min=2, help="Minimum distinct funded wallets for a fan-out hub."
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Build native funding edges, fan-out hubs, and fresh-wallet rows."""
    case = ctx.obj
    with console.status("[bold cyan]Building the funding graph..."):
        summary = case.analyze_funding(fresh_nonce=fresh_nonce, hub_min=hub_min)
    if as_json:
        _print_json(summary)
    else:
        _funding_tables(summary)


@analyze_app.command("provenance")
def analyze_provenance_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    top: int = typer.Option(15, min=1, max=200, help="Wallets to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Compare first native funding with first-trade timing per wallet."""
    case = ctx.obj
    with console.status("[bold cyan]Joining funding provenance..."):
        summary = case.analyze_provenance(minutes)
    if as_json:
        _print_json(summary)
    else:
        _provenance_tables(summary, top)


@analyze_app.command("wallets")
def analyze_wallets_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(..., min=1),
    sort: str = typer.Option(
        "net", help="Rank by net, roi, impact, fees, or retention."
    ),
    top: int = typer.Option(15, min=1, max=200, help="Rows to display."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Join wallet PnL, fees, execution, flow, and funding evidence."""
    case = ctx.obj
    sort = sort.lower()
    if sort not in {"net", "roi", "impact", "fees", "retention"}:
        raise typer.BadParameter("--sort must be net, roi, impact, fees, or retention")
    with console.status("[bold cyan]Joining wallet scorecard..."):
        summary = case.analyze_wallets(minutes)
    if as_json:
        _print_json(summary)
    else:
        _wallet_scorecard_tables(summary, top, sort)
