"""Optional Typer CLI adapter over :class:`LaunchRun`.

The analysis library never imports this module. Install ``pons-analysis[cli]`` to
use the console interface.
"""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.traceback import install

from pons_analysis.config import CachePolicy, RunConfig
from pons_analysis.core.errors import ConfigurationError, PonsError
from pons_analysis.core.models import Launch, MigrationCut
from pons_analysis.credentials import Credentials
from pons_analysis.pons import Pons
from pons_analysis.run import LaunchRun

app = typer.Typer(
    help="Read-only PONS launch and EVM analysis.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
collect_app = typer.Typer(help="Collect provider evidence.", no_args_is_help=True)
analyze_app = typer.Typer(
    help="Recompute analyses from artifacts.", no_args_is_help=True
)
cache_app = typer.Typer(help="Inspect or clear provider caches.", no_args_is_help=True)
app.add_typer(collect_app, name="collect")
app.add_typer(analyze_app, name="analyze")
app.add_typer(cache_app, name="cache")
console = Console()


def _print_json(payload) -> None:
    """Write unwrapped JSON; Rich's JSON renderer can wrap long strings."""
    if hasattr(payload, "as_dict"):
        payload = payload.as_dict()
    typer.echo(json.dumps(payload, default=str))


class CliSession:
    """Persist-by-default adapter used by the command renderers."""

    def __init__(self, run: LaunchRun):
        self.run = run
        self.store = run.store
        self.launch = run.launch

    def close(self) -> None:
        self.run.close()

    def collect_launch(self, **kwargs):
        return self.run.collect_launch(**kwargs)

    def collect_window(self, minutes, **kwargs):
        return self.run.collect_window(minutes, **kwargs)

    def collect_successors(self, wallets, **kwargs):
        return self.run.collect_successors(wallets, **kwargs)

    def collect_funding(self, wallets, **kwargs):
        return self.run.collect_funding(wallets, **kwargs)

    def analyze_launch(self):
        return self.run.launch_analysis(persist=True)

    def analyze_window(self, minutes, *, cohort=()):
        return self.run.window(minutes, cohort=cohort, persist=True)

    def analyze_positions(self, minutes, *, cohort=()):
        return self.run.positions(minutes, cohort=cohort, persist=True)

    def analyze_route_performance(self, minutes):
        return self.run.route_performance(minutes, persist=True)

    def analyze_lifecycle(self, minutes):
        return self.run.lifecycle(minutes, persist=True)

    def analyze_entry_cohorts(self, minutes, *, bucket=60):
        return self.run.entry_cohorts(minutes, bucket=bucket, persist=True)

    def analyze_retention(self, minutes, *, bucket=60):
        return self.run.retention(minutes, bucket=bucket, persist=True)

    def analyze_trajectory(self, minutes):
        return self.run.trajectory(minutes, persist=True)

    def analyze_candles(self, minutes, *, bucket=60):
        return self.run.candles(minutes, bucket=bucket, persist=True)

    def analyze_flow(self, minutes, *, bucket=60):
        return self.run.flow(minutes, bucket=bucket, persist=True)

    def analyze_holders(self, minutes, *, bucket=60):
        return self.run.holders(minutes, bucket=bucket, persist=True)

    def analyze_execution(self, minutes):
        return self.run.execution(minutes, persist=True)

    def analyze_cohort(self, minutes, *, cohort=()):
        return self.run.cohort(minutes, cohort=cohort, persist=True)

    def analyze_clusters(self, minutes, *, fresh_nonce=10, min_timing=3):
        return self.run.clusters(
            minutes,
            fresh_nonce=fresh_nonce,
            min_timing=min_timing,
            persist=True,
        )

    def analyze_cluster_quality(self, minutes):
        return self.run.cluster_quality(minutes, persist=True)

    def analyze_fees(self, minutes):
        return self.run.fees(minutes, persist=True)

    def analyze_funding(self, *, fresh_nonce=10, hub_min=3):
        return self.run.funding(fresh_nonce=fresh_nonce, hub_min=hub_min, persist=True)

    def analyze_provenance(self, minutes):
        return self.run.provenance(minutes, persist=True)

    def analyze_wallets(self, minutes):
        return self.run.wallets(minutes, persist=True)

    def refresh(self, minutes, *, cohort=()):
        return self.run.refresh(minutes, cohort=cohort, persist=True)

    def compare(self, left: int, right: int, *, output: str | None = None):
        return self.run.compare(left, right, output=output, persist=True)

    def render_report(self, minutes, *, cohort=(), output="analysis/report.html"):
        from pons_analysis.presentation.report import render_report

        return render_report(
            self.store,
            self.launch,
            minutes=minutes,
            cohort=cohort,
            output=output,
        )

    def validate(self):
        return self.run.validate(persist=True)

    def validate_derived(self, minutes=30):
        return self.run.validate_derived(minutes, persist=True)

    def manifest(self):
        return self.run.manifest()


def _migration_cut(
    block: int,
    tx_index: int | None,
    log_index: int | None,
) -> MigrationCut:
    if tx_index is None or log_index is None:
        raise ConfigurationError(
            "--migration-block requires --migration-tx-index and --migration-log-index"
        )
    return MigrationCut(block=block, tx_index=tx_index, log_index=log_index)


def _launch_from_options(
    token: str,
    *,
    migration_block: int | None,
    migration_tx_index: int | None,
    migration_log_index: int | None,
    start_timestamp: int | None,
    launch_start_block: int | None,
    pool_id: str | None,
    supply: int | None,
    decimals: int | None,
) -> Launch:
    if supply is None or start_timestamp is None:
        raise ConfigurationError(
            "Supply and start timestamp are required for explicit launches"
        )
    if migration_block is not None:
        start_block = migration_block
        migration = _migration_cut(
            migration_block, migration_tx_index, migration_log_index
        )
    else:
        if launch_start_block is None:
            raise ConfigurationError(
                "A curve launch requires --launch-start-block and --start-timestamp"
            )
        start_block = launch_start_block
        migration = None
    return Pons.launch(
        token=token,
        supply=supply,
        decimals=18 if decimals is None else decimals,
        start_block=start_block,
        start_timestamp=start_timestamp,
        launch_start_block=launch_start_block,
        migration=migration,
        pool_id=pool_id,
    )


class LazySession:
    """Build the network session only when a command actually needs it."""

    __slots__ = ("_factory", "_session")

    def __init__(self, factory):
        self._factory = factory
        self._session: CliSession | None = None

    def _get(self) -> CliSession:
        if self._session is None:
            try:
                self._session = self._factory()
            except (PonsError, ValueError) as exc:
                console.print(Panel(str(exc), title="Configuration error", style="red"))
                raise typer.Exit(1) from exc
        return self._session

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()


def _build_session(
    token: str | None,
    *,
    workspace: Path,
    offline: bool,
    credentials_file: Path | None,
    migration_block: int | None,
    migration_tx_index: int | None,
    migration_log_index: int | None,
    start_timestamp: int | None,
    launch_start_block: int | None,
    pool_id: str | None,
    supply: int | None,
    decimals: int | None,
) -> CliSession:
    if token is None:
        raise ConfigurationError("Missing --token or PONS_TOKEN")
    credentials = (
        Credentials.from_file(credentials_file)
        if credentials_file is not None
        else Credentials.from_env()
    )
    config = RunConfig(
        cache=CachePolicy.OFFLINE if offline else CachePolicy.ONLINE,
        persist=True,
    )
    if (
        supply is not None
        and start_timestamp is not None
        and (migration_block is not None or launch_start_block is not None)
    ):
        launch = _launch_from_options(
            token,
            migration_block=migration_block,
            migration_tx_index=migration_tx_index,
            migration_log_index=migration_log_index,
            start_timestamp=start_timestamp,
            launch_start_block=launch_start_block,
            pool_id=pool_id,
            supply=supply,
            decimals=decimals,
        )
        run = LaunchRun(
            launch,
            workspace,
            credentials=credentials,
            config=config,
        )
    else:
        if start_timestamp is not None:
            raise ConfigurationError(
                "--start-timestamp requires --supply and either "
                "--migration-block or --launch-start-block"
            )
        discover_kwargs = {}
        if launch_start_block is not None:
            discover_kwargs["launch_start_block"] = launch_start_block
        if migration_block is not None:
            discover_kwargs["migration"] = _migration_cut(
                migration_block, migration_tx_index, migration_log_index
            )
        if pool_id is not None:
            discover_kwargs["pool_id"] = pool_id
        if supply is not None:
            discover_kwargs["supply"] = supply
        if decimals is not None:
            discover_kwargs["decimals"] = decimals
        run = LaunchRun.discover(
            token,
            workspace=workspace,
            credentials=credentials,
            config=config,
            **discover_kwargs,
        )
    return CliSession(run)


@app.callback()
def main(
    ctx: typer.Context,
    token: str | None = typer.Option(
        None, "--token", help="PONS token address.", envvar="PONS_TOKEN"
    ),
    workspace: Path = typer.Option(
        Path("."), help="Artifact workspace root.", envvar="PONS_WORKSPACE"
    ),
    offline: bool = typer.Option(
        False, help="Require matching cached responses.", envvar="PONS_OFFLINE"
    ),
    credentials_file: Path | None = typer.Option(
        None, help="JSON or legacy key file with API credentials."
    ),
    migration_block: int | None = typer.Option(
        None, help="Explicit migration block; omit to discover on-chain."
    ),
    migration_tx_index: int | None = typer.Option(
        None, help="Migration transaction index; required with --migration-block."
    ),
    migration_log_index: int | None = typer.Option(
        None, help="Migration log index; required with --migration-block."
    ),
    start_timestamp: int | None = typer.Option(
        None, help="Explicit migration timestamp."
    ),
    launch_start_block: int | None = typer.Option(
        None, help="Explicit pre-launch start block."
    ),
    pool_id: str | None = typer.Option(None, help="Explicit v4 pool id."),
    supply: int | None = typer.Option(
        None, help="Explicit token supply in base units."
    ),
    decimals: int | None = typer.Option(None, help="Token decimals."),
):
    session = LazySession(
        lambda: _build_session(
            token,
            workspace=workspace,
            offline=offline,
            credentials_file=credentials_file,
            migration_block=migration_block,
            migration_tx_index=migration_tx_index,
            migration_log_index=migration_log_index,
            start_timestamp=start_timestamp,
            launch_start_block=launch_start_block,
            pool_id=pool_id,
            supply=supply,
            decimals=decimals,
        )
    )
    ctx.obj = session
    ctx.call_on_close(session.close)


def run() -> None:
    install(show_locals=False)
    try:
        app()
    except (PonsError, ValueError) as exc:
        console.print(Panel(str(exc), title="Analysis failed", style="red"))
        raise SystemExit(1) from exc
