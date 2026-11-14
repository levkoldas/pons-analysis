"""Validation report renderers."""

from rich.table import Table

from ..runtime import console


def _validation_tables(report: dict, *, full: bool = False) -> None:
    checks = report.get("checks") or []
    failures = [check for check in checks if not check.get("ok")]
    rows = checks if full else failures
    if rows:
        table = Table(title="Evidence validation")
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center", no_wrap=True)
        table.add_column("Detail")
        for check in rows:
            detail = str(check.get("detail", ""))
            if not check.get("ok") and check.get("path"):
                detail = f"{detail} · {check['path']}"
            table.add_row(
                check.get("check", ""),
                "[green]ok[/green]" if check.get("ok") else "[red]FAIL[/red]",
                detail,
            )
        console.print(table)
    if report.get("passed"):
        console.print(f"[green]All {len(checks)} checks passed.[/green]")
    else:
        console.print(
            f"[red]{report.get('failures', 0)} of {len(checks)} checks failed.[/red]"
        )


def _derived_validation_tables(report: dict, *, full: bool = False) -> None:
    checks = report.get("results") or []
    failures = [check for check in checks if not check.get("ok")]
    rows = checks if full else failures
    if rows:
        table = Table(title="Derived validation")
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center", no_wrap=True)
        table.add_column("Detail")
        for check in rows:
            table.add_row(
                check.get("name", ""),
                "[green]ok[/green]" if check.get("ok") else "[red]FAIL[/red]",
                str(check.get("detail", "")),
            )
        console.print(table)
    if report.get("passed"):
        console.print(f"[green]All {len(checks)} checks passed.[/green]")
    else:
        console.print(f"[red]{len(failures)} of {len(checks)} checks failed.[/red]")
