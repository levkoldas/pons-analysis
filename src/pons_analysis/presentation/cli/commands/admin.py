"""Workspace administration, reporting, and validation commands."""

import json
from dataclasses import asdict
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from pons_analysis.core.errors import PonsError

from ..renderers.report import _report_tables
from ..renderers.summary import _comparison_tables
from ..renderers.validation import _derived_validation_tables, _validation_tables
from ..runtime import _print_json, app, cache_app, console
from .helpers import _cohort_roots


@app.command()
def profile(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")):
    """Show the active protocol profile and its built-in names."""
    case = ctx.obj
    launch = case.launch
    payload = {
        "name": launch.name,
        "chain": launch.chain,
        "chain_id": launch.chain_id,
        "token": launch.token,
        "decimals": launch.decimals,
        "supply": str(launch.supply),
        "start_block": launch.start_block,
        "start_timestamp": launch.start_timestamp,
        "launch_start_block": launch.launch_start_block,
        "pool_id": launch.pool_id,
        "migration": (
            launch.migration.model_dump(mode="json")
            if launch.migration is not None
            else None
        ),
        "protocol": asdict(launch.protocol),
    }
    if as_json:
        _print_json(payload)
        return
    table = Table(title=f"Launch · {case.profile.name}", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def compare(
    ctx: typer.Context,
    left: int = typer.Argument(..., min=1, help="Baseline window minutes."),
    right: int = typer.Argument(..., min=1, help="Comparison window minutes."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Compare two analyzed windows and write a deterministic summary."""
    case = ctx.obj
    if left == right:
        raise typer.BadParameter("Window durations must differ")
    try:
        summary = case.compare(left, right)
    except PonsError as exc:
        console.print(Panel(str(exc), title="Comparison error", style="red"))
        raise typer.Exit(1) from exc
    if as_json:
        _print_json(summary)
    else:
        _comparison_tables(summary)


@app.command("manifest")
def manifest(ctx: typer.Context, full: bool = typer.Option(False, "--full")):
    """Write and summarize a SHA-256 manifest of every workspace artifact."""
    case = ctx.obj
    data = case.manifest()
    files = data["files"]
    table = Table(title="Artifact manifest")
    table.add_column("Path")
    table.add_column("Bytes", justify="right")
    table.add_column("SHA-256")
    rows = files.items() if full else list(files.items())[:20]
    for path, meta in rows:
        table.add_row(path, f"{meta['bytes']:,}", meta["sha256"][:16] + "…")
    console.print(table)
    console.print(
        f"[dim]{len(files)} files · {sum(item['bytes'] for item in files.values()):,} bytes[/dim]"
    )


@app.command("report")
def render_report_cmd(
    ctx: typer.Context,
    minutes: int = typer.Option(30, min=1, help="Analysis window in minutes."),
    cohort: list[str] = typer.Option([], "--cohort", help="Cohort wallet to include."),
    cohort_file: Path | None = typer.Option(
        None, help="JSON list or CSV with a destination_wallet column."
    ),
    output: Path = typer.Option(
        Path("analysis/report.html"), help="Workspace output under analysis/."
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Render a deterministic standalone HTML/JSON report from derived artifacts."""
    case = ctx.obj
    roots = _cohort_roots(case, cohort, cohort_file)
    with console.status("[bold cyan]Rendering the report..."):
        data = case.render_report(minutes, cohort=roots, output=output)
    if as_json:
        _print_json(data)
        return
    _report_tables(data)


@app.command("validate")
def validate_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json"),
    full: bool = typer.Option(
        False, "--full", help="Show every check, not only failures."
    ),
):
    """Validate launch, window, and funding evidence without rewriting it."""
    report = ctx.obj.validate()
    if as_json:
        _print_json(report)
    else:
        _validation_tables(report, full=full)
    if not report["passed"]:
        raise typer.Exit(1)


@app.command("validate-derived")
def validate_derived_cmd(
    ctx: typer.Context,
    minutes: int = typer.Argument(30, min=1),
    as_json: bool = typer.Option(False, "--json"),
    full: bool = typer.Option(
        False, "--full", help="Show every check, not only failures."
    ),
):
    """Validate derived artifact consistency and report source hashes."""
    report = ctx.obj.validate_derived(minutes)
    if as_json:
        _print_json(report)
    else:
        _derived_validation_tables(report, full=full)
    if not report["passed"]:
        raise typer.Exit(1)


@cache_app.command("clear")
def cache_clear(
    ctx: typer.Context,
    namespace: str | None = typer.Option(None, help="rpc, blockscout, or gmgn."),
):
    """Delete cached provider responses."""
    removed = ctx.obj.store.clear_cache(namespace)
    console.print(f"Removed [bold]{removed}[/bold] cache records.")
