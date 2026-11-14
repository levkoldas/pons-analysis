"""High-level library session for one token launch.

``LaunchRun`` owns provider construction, raw evidence collection, analysis
execution, and optional persistence. It never reads environment variables or the
current working directory implicitly.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pons_analysis.analytics import positions as positions_analysis
from pons_analysis.analytics.clusters import graph as clusters_analysis
from pons_analysis.analytics.clusters import quality as cluster_quality_analysis
from pons_analysis.analytics.cohorts import entry as entry_cohorts_analysis
from pons_analysis.analytics.cohorts import launch_to_exit as cohort_analysis
from pons_analysis.analytics.cohorts import lifecycle as lifecycle_analysis
from pons_analysis.analytics.cohorts import retention as retention_analysis
from pons_analysis.analytics.comparison import compare_windows
from pons_analysis.analytics.funding import graph as funding_analysis
from pons_analysis.analytics.funding import provenance as provenance_analysis
from pons_analysis.analytics.market import candles as candles_analysis
from pons_analysis.analytics.market import execution as execution_analysis
from pons_analysis.analytics.market import fees as fees_analysis
from pons_analysis.analytics.market import flow as flow_analysis
from pons_analysis.analytics.market import holders as holders_analysis
from pons_analysis.analytics.market import launch as launch_analysis
from pons_analysis.analytics.market import trajectory as trajectory_analysis
from pons_analysis.analytics.market import window as window_analysis
from pons_analysis.analytics.routes import performance as route_performance_analysis
from pons_analysis.analytics.wallets import scorecard as wallets_analysis
from pons_analysis.config import RunConfig
from pons_analysis.core.errors import (
    IncompleteHistory,
    InvariantError,
    ProviderError,
    ResolutionError,
)
from pons_analysis.core.evm import addr
from pons_analysis.core.models import Coverage, Launch, LaunchRecord, RpcLog, RpcReceipt
from pons_analysis.credentials import Credentials
from pons_analysis.discovery import read_launch_record
from pons_analysis.evidence import funding as funding_collection
from pons_analysis.evidence import successors as successors_collection
from pons_analysis.pons import Pons
from pons_analysis.providers.blockscout import BlockscoutProvider
from pons_analysis.providers.gmgn import GmgnProvider
from pons_analysis.providers.http import HttpClient
from pons_analysis.providers.rpc import RpcProvider
from pons_analysis.results import (
    AnalysisResult,
    CandlesResult,
    ClusterQualityResult,
    ClustersResult,
    CohortResult,
    ComparisonResult,
    EntryCohortsResult,
    ExecutionResult,
    FeesResult,
    FlowResult,
    FundingResult,
    HoldersResult,
    LaunchResult,
    LifecycleResult,
    PositionsResult,
    ProvenanceResult,
    RefreshResult,
    RetentionResult,
    RoutePerformanceResult,
    Table,
    TrajectoryResult,
    ValidationResult,
    WalletsResult,
    WindowResult,
)
from pons_analysis.storage.overlay import OverlayStore
from pons_analysis.storage.store import ArtifactStore
from pons_analysis.validation.derived import validate_derived
from pons_analysis.validation.raw.audit import validate_workspace

_TABLE_FILES = {
    "launch": {
        "trades": "trades.csv",
        "transfers": "transfers.csv",
        "wallets": "wallets.csv",
        "holders": "holders.csv",
        "routes": "routes.csv",
    },
    "window": {
        "rotations": "rotations.csv",
        "original_wallets": "original_wallets.csv",
        "cohort_holdings_timeline": "cohort_holdings_timeline.csv",
        "five_minute_summary": "five_minute_summary.csv",
    },
    "positions": {
        "positions": "positions.csv",
        "lots": "lots.csv",
        "trade_legs": "trade_legs.csv",
        "transactions": "transactions.csv",
    },
    "route_performance": {"routes": "routes.csv", "wallets": "wallets.csv"},
    "wallets": {"wallets": "wallets.csv"},
    "entry_cohorts": {"cohorts": "cohorts.csv", "wallets": "wallets.csv"},
    "retention": {
        "cohorts": "cohorts.csv",
        "timeline": "timeline.csv",
        "wallets": "wallets.csv",
    },
    "lifecycle": {"groups": "groups.csv", "wallets": "wallets.csv"},
    "trajectory": {"trajectory": "trajectory.csv"},
    "candles": {"candles": "candles.csv", "volume_profile": "volume_profile.csv"},
    "flow": {"buckets": "buckets.csv", "wallets": "wallets.csv"},
    "holders": {"timeline": "timeline.csv"},
    "execution": {"wallets": "wallets.csv", "groups": "groups.csv"},
    "cohort": {
        "generations": "generations.csv",
        "terminal_holders": "terminal_holders.csv",
    },
    "clusters": {
        "clusters": "clusters.csv",
        "wallets": "wallets.csv",
        "edges": "edges.csv",
        "round_trips": "round_trips.csv",
    },
    "cluster_quality": {"clusters": "clusters.csv"},
    "fees": {"groups": "groups.csv", "wallets": "wallets.csv"},
    "funding": {
        "edges": "edges.csv",
        "wallets": "wallets.csv",
        "counterparties": "counterparties.csv",
    },
    "provenance": {"wallets": "wallets.csv"},
    "validation": {},
}


class LaunchRun:
    """A bound protocol launch, workspace, providers, and analysis session."""

    def __init__(
        self,
        launch: Launch,
        workspace: str | Path,
        *,
        credentials: Credentials | None = None,
        config: RunConfig | None = None,
        store: ArtifactStore | None = None,
        http: HttpClient | None = None,
    ):
        self.launch = launch
        self.config = config or RunConfig()
        self.credentials = credentials or Credentials()
        self.workspace = Path(workspace).expanduser().resolve()
        self.store = store or ArtifactStore(self.workspace)
        self._owns_http = http is None
        self.http = http or HttpClient(self.config)
        policy = self.config.cache_policy
        endpoints = self.config.rpc_endpoints or launch.rpc_endpoints
        self.rpc = RpcProvider(
            self.http,
            self.store,
            endpoints=endpoints,
            chain_id=launch.chain_id,
            cache_policy=policy,
        )
        self.blockscout = BlockscoutProvider(
            self.http,
            self.store,
            self.config,
            self.credentials,
            chain_id=launch.chain_id,
            cache_policy=policy,
        )
        self.gmgn = GmgnProvider(
            self.http,
            self.store,
            self.config,
            self.credentials,
            chain=launch.chain,
            token=launch.token,
            cache_policy=policy,
        )

    @classmethod
    def discover(
        cls,
        token: str,
        *,
        workspace: str | Path,
        credentials: Credentials | None = None,
        config: RunConfig | None = None,
        **resolve_kwargs: Any,
    ) -> LaunchRun:
        """Resolve a token launch from on-chain metadata, then bind a session."""

        config = config or RunConfig()
        credentials = credentials or Credentials()
        root = Path(workspace).expanduser().resolve()
        store = ArtifactStore(root)
        resolve_kwargs = dict(resolve_kwargs)
        with HttpClient(config) as http:
            rpc = RpcProvider(
                http,
                store,
                endpoints=config.rpc_endpoints or Pons.protocol.rpc_endpoints,
                chain_id=Pons.protocol.chain_id,
                cache_policy=config.cache_policy,
            )
            if "launch_start_block" not in resolve_kwargs:
                try:
                    resolve_kwargs["launch_start_block"] = rpc.creation_block(token)
                except ProviderError:
                    if not credentials.get("blockscout"):
                        raise
                    blockscout = BlockscoutProvider(
                        http,
                        store,
                        config,
                        credentials,
                        chain_id=Pons.protocol.chain_id,
                        cache_policy=config.cache_policy,
                    )
                    try:
                        resolve_kwargs["launch_start_block"] = (
                            blockscout.creation_block(token)
                        )
                    except ProviderError as fallback:
                        raise ResolutionError(
                            "Cannot discover the token deployment block from RPC "
                            "or Blockscout; pass launch_start_block"
                        ) from fallback
            launch = Pons.resolve(token, rpc=rpc, **resolve_kwargs)
        return cls(
            launch,
            root,
            credentials=credentials,
            config=config,
            store=store,
        )

    def __enter__(self) -> LaunchRun:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    # ---- shared hydration --------------------------------------------------

    def _hydrate(
        self,
        hashes: Iterable[str],
        directory: str,
        *,
        existing_receipts: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[int, int]]:
        hashes = sorted(set(hashes))
        known: dict[str, dict[str, Any]] = {
            receipt["transactionHash"]: receipt for receipt in (existing_receipts or [])
        }
        missing = [tx_hash for tx_hash in hashes if tx_hash not in known]
        with ThreadPoolExecutor(self.config.max_workers) as workers:
            fetched = list(workers.map(self.rpc.receipt, missing))
        for receipt in fetched:
            known[receipt.transaction_hash] = receipt.model_dump(
                mode="json", by_alias=True
            )
        receipts: list[dict[str, Any]] = [known[tx_hash] for tx_hash in hashes]
        heights = sorted(
            {RpcReceipt.model_validate(row).block_number for row in receipts}
        )
        with ThreadPoolExecutor(self.config.max_workers) as workers:
            blocks = list(workers.map(self.rpc.block, heights))
        timestamps = {block.number: block.timestamp for block in blocks}
        for row in receipts:
            row["block_timestamp"] = timestamps[
                RpcReceipt.model_validate(row).block_number
            ]
        self.store.write_json(f"{directory}/receipts.json", receipts)
        self.store.write_json(
            f"{directory}/blocks.json",
            {
                str(block.number): block.model_dump(mode="json", by_alias=True)
                for block in blocks
            },
        )
        return receipts, timestamps

    def _transactions(self, hashes: Iterable[str], directory: str) -> None:
        hashes = sorted(set(hashes))
        with ThreadPoolExecutor(self.config.max_workers) as workers:
            rows = list(workers.map(self.rpc.transaction, hashes))
        self.store.write_json(
            f"{directory}/txs.json",
            {row.hash: row.model_dump(mode="json", by_alias=True) for row in rows},
        )

    def _record(self, block: int | str = "latest") -> LaunchRecord:
        existing = self.store.read_json(
            "evidence/launch/record.json", model=LaunchRecord
        )
        if existing is not None:
            if existing.token != self.launch.token:
                raise InvariantError("Cached launch record belongs to another token")
            return existing
        record = read_launch_record(
            self.rpc, self.launch.protocol, self.launch.token, block=block
        )
        if record.token != self.launch.token:
            raise InvariantError("Factory record token does not match the launch")
        return record

    # ---- collection --------------------------------------------------------

    def collect_launch(self, *, head: int | None = None) -> dict[str, Any]:
        launch = self.launch
        head = self.rpc.latest_block() if head is None else head
        end = launch.migration.block if launch.migration is not None else head
        if head < end:
            raise InvariantError("Coverage head cannot precede the analysis end block")
        start = (
            launch.launch_start_block
            if launch.launch_start_block is not None
            else launch.start_block
        )
        record = self._record(head)
        if launch.migration is None and record.phase is not None and record.phase >= 2:
            raise InvariantError(
                "Launch has migrated since discovery; rediscover the token "
                "before collecting post-migration evidence"
            )
        transfers = self.rpc.logs(launch.token, start, end, [launch.transfer_topic])
        curve_logs = self.rpc.logs(record.curve, start, end) if record.curve else []
        swaps = (
            self.rpc.logs(
                launch.manager,
                start,
                end,
                [launch.swap_topic, launch.pool_id],
            )
            if launch.swap_topic and launch.pool_id
            else []
        )
        hashes = {log.transaction_hash for log in transfers + curve_logs + swaps}
        receipts, timestamps = self._hydrate(hashes, "evidence/launch")
        edge_numbers = {start, end, head}
        if end + 1 <= head:
            edge_numbers.add(end + 1)
        edge_blocks = {
            number: self.rpc.block(number) for number in sorted(edge_numbers)
        }
        blocks = self.store.read_json("evidence/launch/blocks.json") or {}
        blocks.update(
            {
                str(number): block.model_dump(mode="json", by_alias=True)
                for number, block in edge_blocks.items()
            }
        )
        self.store.write_json("evidence/launch/blocks.json", blocks)
        timestamps.update(
            {number: block.timestamp for number, block in edge_blocks.items()}
        )
        self._transactions(hashes, "evidence/launch")
        self.store.write_json(
            "evidence/launch/transfers.json",
            [log.model_dump(mode="json", by_alias=True) for log in transfers],
        )
        self.store.write_json(
            "evidence/launch/curve_logs.json",
            [log.model_dump(mode="json", by_alias=True) for log in curve_logs],
        )
        self.store.write_json(
            "evidence/launch/swaps.json",
            [log.model_dump(mode="json", by_alias=True) for log in swaps],
        )
        self.store.write_json(
            "evidence/launch/record.json", record.model_dump(mode="json", by_alias=True)
        )
        start_timestamp = timestamps[start]
        end_timestamp = timestamps[end]
        coverage = Coverage(
            start_block=start,
            end_block=end,
            start_timestamp=start_timestamp,
            end_timestamp_exclusive=end_timestamp + 1,
            head=head,
            transactions=len(receipts),
            next_block_timestamp=timestamps.get(end + 1),
            end_block_timestamp=end_timestamp,
        )
        self.store.write_json(
            "evidence/launch/coverage.json", coverage.model_dump(mode="json")
        )
        return coverage.model_dump(mode="json")

    def collect_window(
        self,
        minutes: int,
        *,
        prior_minutes: int | None = None,
        with_activity: bool = False,
        head: int | None = None,
    ) -> dict[str, Any]:
        if minutes <= 0:
            raise ValueError("Window minutes must be positive")
        launch = self.launch
        collect_curve = launch.migration is None and launch.curve is not None
        start = launch.start_timestamp
        end = start + minutes * 60
        directory = f"evidence/windows/{minutes}"
        start_block = launch.start_block
        existing_bounds = self.store.read_json(f"{directory}/bounds.json")
        reusable = (
            self.config.offline
            and existing_bounds is not None
            and existing_bounds.get("start_timestamp") == start
            and existing_bounds.get("end_timestamp_exclusive") == end
            and self.store.exists(f"{directory}/token_logs.json")
            and self.store.exists(f"{directory}/swaps_logs.json")
            and self.store.exists(f"{directory}/receipts.json")
            and self.store.exists(f"{directory}/blocks.json")
            and (not collect_curve or self.store.exists(f"{directory}/curve_logs.json"))
        )
        if reusable:
            if with_activity and not self.store.exists(f"{directory}/activities.json"):
                token_logs = [
                    RpcLog.model_validate(item)
                    for item in self.store.read_json(f"{directory}/token_logs.json")
                ]
                addresses = {addr(log.topics[1]) for log in token_logs} | {
                    addr(log.topics[2]) for log in token_logs
                }
                activities = []
                for address in sorted(addresses):
                    history = self.gmgn.wallet_activity(address)
                    if not history.complete:
                        raise IncompleteHistory(history.model_dump())
                    activities.extend(history.items)
                self.store.write_json(f"{directory}/activities.json", activities)
            return existing_bounds
        if head is None:
            if self.config.offline:
                raise InvariantError("Offline window collection requires a head")
            head = self.rpc.latest_block()
        end_block = self.rpc.find_block_by_timestamp(end, start_block, head) - 1
        previous = start_block - 1
        prior_logs: dict[str, list[RpcLog]] = {
            "token_logs": [],
            "swaps_logs": [],
            "curve_logs": [],
        }
        prior_receipts: list[dict[str, Any]] = []
        if prior_minutes is not None:
            prior_dir = f"evidence/windows/{prior_minutes}"
            prior_bounds = self.store.read_json(f"{prior_dir}/bounds.json")
            if prior_bounds is None:
                raise InvariantError("Prior window snapshot is missing")
            if int(prior_bounds["start_block"]) != start_block:
                raise InvariantError("Prior snapshot covers a different launch")
            if prior_bounds["end_block"] > end_block:
                raise InvariantError(
                    "Prior snapshot extends beyond the requested window"
                )
            previous = prior_bounds["end_block"]
            loaded_receipts = self.store.read_json(f"{prior_dir}/receipts.json")
            if loaded_receipts is None:
                raise InvariantError("Prior window receipts are missing")
            prior_receipts = loaded_receipts
            for name in prior_logs:
                payload = self.store.read_json(f"{prior_dir}/{name}.json")
                if payload is None:
                    raise InvariantError(f"Prior window {name} are missing")
                prior_logs[name] = [RpcLog.model_validate(item) for item in payload]

        token_logs = list(prior_logs["token_logs"])
        swaps = list(prior_logs["swaps_logs"])
        curve_logs = list(prior_logs["curve_logs"])
        for low in range(previous + 1, end_block + 1, 2_000):
            high = min(low + 1_999, end_block)
            token_logs.extend(
                self.rpc.logs(launch.token, low, high, [launch.transfer_topic])
            )
            if launch.swap_topic and launch.pool_id:
                swaps.extend(
                    self.rpc.logs(
                        launch.manager,
                        low,
                        high,
                        [launch.swap_topic, launch.pool_id],
                    )
                )
            if collect_curve and launch.curve is not None:
                curve_logs.extend(self.rpc.logs(launch.curve, low, high))
        events = token_logs + swaps + curve_logs
        keys = {(log.transaction_hash, log.log_index) for log in events}
        if len(keys) != len(events):
            raise InvariantError("Duplicate events in window snapshot")
        receipts, timestamps = self._hydrate(
            {log.transaction_hash for log in events},
            directory,
            existing_receipts=prior_receipts,
        )
        edge_numbers = [end_block]
        if end_block < head:
            edge_numbers.append(end_block + 1)
        edge_blocks = {number: self.rpc.block(number) for number in edge_numbers}
        blocks = self.store.read_json(f"{directory}/blocks.json") or {}
        blocks.update(
            {
                str(number): block.model_dump(mode="json", by_alias=True)
                for number, block in edge_blocks.items()
            }
        )
        self.store.write_json(f"{directory}/blocks.json", blocks)
        timestamps.update(
            {number: block.timestamp for number, block in edge_blocks.items()}
        )
        for receipt in receipts:
            timestamp = receipt.get("block_timestamp")
            if timestamp is None and timestamps:
                timestamp = timestamps[RpcReceipt.model_validate(receipt).block_number]
            if timestamp is None or not start <= int(timestamp) < end:
                raise InvariantError("Receipt outside the requested window")
        self.store.write_json(
            f"{directory}/token_logs.json",
            [log.model_dump(mode="json", by_alias=True) for log in token_logs],
        )
        self.store.write_json(
            f"{directory}/swaps_logs.json",
            [log.model_dump(mode="json", by_alias=True) for log in swaps],
        )
        self.store.write_json(
            f"{directory}/curve_logs.json",
            [log.model_dump(mode="json", by_alias=True) for log in curve_logs],
        )
        bounds = {
            "start_timestamp": start,
            "end_timestamp_exclusive": end,
            "start_block": start_block,
            "end_block": end_block,
            "head": head,
            "next_block_timestamp": timestamps.get(end_block + 1),
            "end_block_timestamp": timestamps.get(end_block),
        }
        self.store.write_json(f"{directory}/bounds.json", bounds)
        if with_activity:
            addresses = {addr(log.topics[1]) for log in token_logs} | {
                addr(log.topics[2]) for log in token_logs
            }
            activities = []
            for address in sorted(addresses):
                history = self.gmgn.wallet_activity(address)
                if not history.complete:
                    raise IncompleteHistory(history.model_dump())
                activities.extend(history.items)
            self.store.write_json(f"{directory}/activities.json", activities)
        return bounds

    def collect_successors(
        self,
        wallets: Iterable[str],
        *,
        start_block: int | None = None,
        with_activity: bool = True,
    ) -> dict[str, Any]:
        result = successors_collection.collect_successors(
            self.rpc,
            self.store,
            self.launch,
            start_block=(
                self.launch.start_block if start_block is None else start_block
            ),
            wallets=wallets,
        )
        if with_activity:
            tracked = (
                self.store.read_json("evidence/successors/tracked_wallets.json") or []
            )
            result["activity"] = successors_collection.collect_wallet_activity(
                self.gmgn, self.store, wallets=tracked
            )
        return result

    def collect_funding(
        self,
        wallets: Iterable[str],
        *,
        start_block: int | None = None,
        cap: int = 100,
    ) -> dict[str, Any]:
        return funding_collection.collect_funding(
            self.blockscout,
            self.rpc,
            self.store,
            wallets=wallets,
            start_block=start_block,
            cap=cap,
            offline=self.config.offline,
        )

    # ---- result construction ----------------------------------------------

    @contextmanager
    def _analysis_scope(
        self,
        persist: bool | None,
        *,
        fallback_analysis: bool = False,
    ) -> Generator[tuple[ArtifactStore, bool]]:
        persist = self.config.persist if persist is None else persist
        if persist:
            yield self.store, True
            return
        with TemporaryDirectory(prefix="pons-analysis-") as directory:
            yield (
                OverlayStore(
                    self.store,
                    directory,
                    fallback_analysis=fallback_analysis,
                ),
                False,
            )

    def _result[ResultT: AnalysisResult](
        self,
        result_type: type[ResultT],
        store: ArtifactStore,
        data: dict[str, Any],
        base: str,
        persisted: bool,
    ) -> ResultT:
        files = _TABLE_FILES.get(result_type.analysis, {})
        tables = {
            name: Table.from_csv(store, f"{base}/{filename}")
            for name, filename in files.items()
        }
        artifacts: list[Path] = []
        if persisted:
            candidates = [f"{base}/summary.json"] + [
                f"{base}/{filename}" for filename in files.values()
            ]
            artifacts = [
                store.path(relative)
                for relative in candidates
                if store.path(relative).exists()
            ]
        return result_type(data, tables, artifacts)

    def _launch_result(self, store: ArtifactStore, persisted: bool) -> LaunchResult:
        data = launch_analysis.analyze_launch(store, self.launch)
        return self._result(LaunchResult, store, data, "analysis/launch", persisted)

    def _window_result(
        self, store: ArtifactStore, minutes: int, cohort: Iterable[str], persisted: bool
    ) -> WindowResult:
        data = window_analysis.analyze_window(
            store, self.launch, minutes=minutes, cohort=cohort
        )
        return self._result(
            WindowResult, store, data, f"analysis/window-{minutes}", persisted
        )

    def _positions_result(
        self, store: ArtifactStore, minutes: int, cohort: Iterable[str], persisted: bool
    ) -> PositionsResult:
        data = positions_analysis.analyze_positions(
            store, self.launch, minutes=minutes, cohort=cohort
        )
        return self._result(
            PositionsResult, store, data, f"analysis/positions-{minutes}", persisted
        )

    def _route_performance_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> RoutePerformanceResult:
        data = route_performance_analysis.analyze_route_performance(
            store, self.launch, minutes=minutes
        )
        return self._result(
            RoutePerformanceResult,
            store,
            data,
            f"analysis/route-performance-{minutes}",
            persisted,
        )

    def _wallets_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> WalletsResult:
        data = wallets_analysis.analyze_wallets(store, self.launch, minutes=minutes)
        return self._result(
            WalletsResult, store, data, f"analysis/wallets-{minutes}", persisted
        )

    def _entry_cohorts_result(
        self, store: ArtifactStore, minutes: int, bucket: int, persisted: bool
    ) -> EntryCohortsResult:
        data = entry_cohorts_analysis.analyze_entry_cohorts(
            store, self.launch, minutes=minutes, bucket=bucket
        )
        return self._result(
            EntryCohortsResult,
            store,
            data,
            f"analysis/entry-cohorts-{minutes}",
            persisted,
        )

    def _retention_result(
        self, store: ArtifactStore, minutes: int, bucket: int, persisted: bool
    ) -> RetentionResult:
        data = retention_analysis.analyze_retention(
            store, self.launch, minutes=minutes, bucket=bucket
        )
        return self._result(
            RetentionResult, store, data, f"analysis/retention-{minutes}", persisted
        )

    def _lifecycle_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> LifecycleResult:
        data = lifecycle_analysis.analyze_lifecycle(store, self.launch, minutes=minutes)
        return self._result(
            LifecycleResult, store, data, f"analysis/lifecycle-{minutes}", persisted
        )

    def _trajectory_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> TrajectoryResult:
        data = trajectory_analysis.analyze_trajectory(
            store, self.launch, minutes=minutes
        )
        return self._result(
            TrajectoryResult, store, data, f"analysis/trajectory-{minutes}", persisted
        )

    def _candles_result(
        self, store: ArtifactStore, minutes: int, bucket: int, persisted: bool
    ) -> CandlesResult:
        data = candles_analysis.analyze_candles(
            store, self.launch, minutes=minutes, bucket=bucket
        )
        return self._result(
            CandlesResult, store, data, f"analysis/candles-{minutes}", persisted
        )

    def _flow_result(
        self, store: ArtifactStore, minutes: int, bucket: int, persisted: bool
    ) -> FlowResult:
        data = flow_analysis.analyze_flow(
            store, self.launch, minutes=minutes, bucket=bucket
        )
        return self._result(
            FlowResult, store, data, f"analysis/flow-{minutes}", persisted
        )

    def _holders_result(
        self, store: ArtifactStore, minutes: int, bucket: int, persisted: bool
    ) -> HoldersResult:
        data = holders_analysis.analyze_holders(
            store, self.launch, minutes=minutes, bucket=bucket
        )
        return self._result(
            HoldersResult, store, data, f"analysis/holders-{minutes}", persisted
        )

    def _execution_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> ExecutionResult:
        data = execution_analysis.analyze_execution(store, self.launch, minutes=minutes)
        return self._result(
            ExecutionResult, store, data, f"analysis/execution-{minutes}", persisted
        )

    def _cohort_result(
        self, store: ArtifactStore, minutes: int, cohort: Iterable[str], persisted: bool
    ) -> CohortResult:
        data = cohort_analysis.analyze_cohort(
            store, self.launch, minutes=minutes, cohort=cohort
        )
        return self._result(
            CohortResult, store, data, f"analysis/cohort-{minutes}", persisted
        )

    def _clusters_result(
        self,
        store: ArtifactStore,
        minutes: int,
        fresh_nonce: int,
        min_timing: int,
        persisted: bool,
    ) -> ClustersResult:
        data = clusters_analysis.analyze_clusters(
            store,
            self.launch,
            minutes=minutes,
            fresh_nonce=fresh_nonce,
            min_timing=min_timing,
        )
        return self._result(ClustersResult, store, data, "analysis/clusters", persisted)

    def _cluster_quality_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> ClusterQualityResult:
        data = cluster_quality_analysis.analyze_cluster_quality(
            store, self.launch, minutes=minutes
        )
        return self._result(
            ClusterQualityResult,
            store,
            data,
            f"analysis/cluster-quality-{minutes}",
            persisted,
        )

    def _fees_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> FeesResult:
        data = fees_analysis.analyze_fees(store, self.launch, minutes=minutes)
        return self._result(
            FeesResult, store, data, f"analysis/fees-{minutes}", persisted
        )

    def _funding_result(
        self,
        store: ArtifactStore,
        fresh_nonce: int,
        hub_min: int,
        persisted: bool,
    ) -> FundingResult:
        data = funding_analysis.analyze_funding(
            store,
            self.launch,
            fresh_nonce=fresh_nonce,
            hub_min=hub_min,
        )
        return self._result(FundingResult, store, data, "analysis/funding", persisted)

    def _provenance_result(
        self, store: ArtifactStore, minutes: int, persisted: bool
    ) -> ProvenanceResult:
        data = provenance_analysis.analyze_provenance(
            store, self.launch, minutes=minutes
        )
        return self._result(
            ProvenanceResult, store, data, f"analysis/provenance-{minutes}", persisted
        )

    def _validation_result(
        self,
        store: ArtifactStore,
        data: dict[str, Any],
        persisted: bool,
        relative: str = "analysis/validation.json",
    ) -> ValidationResult:
        artifacts = (
            (store.path(relative),)
            if persisted and store.path(relative).exists()
            else ()
        )
        return ValidationResult(data, {}, artifacts)

    # ---- public analysis API ----------------------------------------------

    def launch_analysis(self, *, persist: bool | None = None) -> LaunchResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._launch_result(store, persisted)

    def window(
        self,
        minutes: int,
        *,
        cohort: Iterable[str] = (),
        persist: bool | None = None,
    ) -> WindowResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._window_result(store, minutes, cohort, persisted)

    def positions(
        self,
        minutes: int,
        *,
        cohort: Iterable[str] = (),
        persist: bool | None = None,
    ) -> PositionsResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._positions_result(store, minutes, cohort, persisted)

    def route_performance(
        self, minutes: int, *, persist: bool | None = None
    ) -> RoutePerformanceResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._route_performance_result(store, minutes, persisted)

    def wallets(self, minutes: int, *, persist: bool | None = None) -> WalletsResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._wallets_result(store, minutes, persisted)

    def entry_cohorts(
        self,
        minutes: int,
        *,
        bucket: int = 60,
        persist: bool | None = None,
    ) -> EntryCohortsResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._entry_cohorts_result(store, minutes, bucket, persisted)

    def retention(
        self,
        minutes: int,
        *,
        bucket: int = 60,
        persist: bool | None = None,
    ) -> RetentionResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._retention_result(store, minutes, bucket, persisted)

    def lifecycle(
        self, minutes: int, *, persist: bool | None = None
    ) -> LifecycleResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._lifecycle_result(store, minutes, persisted)

    def trajectory(
        self, minutes: int, *, persist: bool | None = None
    ) -> TrajectoryResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._trajectory_result(store, minutes, persisted)

    def candles(
        self,
        minutes: int,
        *,
        bucket: int = 60,
        persist: bool | None = None,
    ) -> CandlesResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._candles_result(store, minutes, bucket, persisted)

    def flow(
        self,
        minutes: int,
        *,
        bucket: int = 60,
        persist: bool | None = None,
    ) -> FlowResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._flow_result(store, minutes, bucket, persisted)

    def holders(
        self,
        minutes: int,
        *,
        bucket: int = 60,
        persist: bool | None = None,
    ) -> HoldersResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._holders_result(store, minutes, bucket, persisted)

    def execution(
        self, minutes: int, *, persist: bool | None = None
    ) -> ExecutionResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._execution_result(store, minutes, persisted)

    def cohort(
        self,
        minutes: int,
        *,
        cohort: Iterable[str],
        persist: bool | None = None,
    ) -> CohortResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._cohort_result(store, minutes, cohort, persisted)

    def clusters(
        self,
        minutes: int,
        *,
        fresh_nonce: int = 10,
        min_timing: int = 3,
        persist: bool | None = None,
    ) -> ClustersResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._clusters_result(
                store, minutes, fresh_nonce, min_timing, persisted
            )

    def cluster_quality(
        self, minutes: int, *, persist: bool | None = None
    ) -> ClusterQualityResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._cluster_quality_result(store, minutes, persisted)

    def fees(self, minutes: int, *, persist: bool | None = None) -> FeesResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._fees_result(store, minutes, persisted)

    def funding(
        self,
        *,
        fresh_nonce: int = 10,
        hub_min: int = 3,
        persist: bool | None = None,
    ) -> FundingResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._funding_result(store, fresh_nonce, hub_min, persisted)

    def provenance(
        self, minutes: int, *, persist: bool | None = None
    ) -> ProvenanceResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._provenance_result(store, minutes, persisted)

    def has_funding(self) -> bool:
        return self.store.is_dir("evidence/funding/wallets")

    def refresh(
        self,
        minutes: int,
        *,
        cohort: Iterable[str] = (),
        persist: bool | None = None,
    ) -> RefreshResult:
        roots = tuple(sorted({addr(item) for item in cohort}))
        with self._analysis_scope(persist) as (store, persisted):
            results: dict[str, AnalysisResult] = {
                "launch": self._launch_result(store, persisted),
                "window": self._window_result(store, minutes, roots, persisted),
                "positions": self._positions_result(store, minutes, roots, persisted),
                "fees": self._fees_result(store, minutes, persisted),
                "route_performance": self._route_performance_result(
                    store, minutes, persisted
                ),
                "lifecycle": self._lifecycle_result(store, minutes, persisted),
                "entry_cohorts": self._entry_cohorts_result(
                    store, minutes, 60, persisted
                ),
                "retention": self._retention_result(store, minutes, 60, persisted),
                "trajectory": self._trajectory_result(store, minutes, persisted),
                "candles": self._candles_result(store, minutes, 60, persisted),
                "flow": self._flow_result(store, minutes, 60, persisted),
                "holders": self._holders_result(store, minutes, 60, persisted),
                "execution": self._execution_result(store, minutes, persisted),
            }
            if self.has_funding():
                results["funding"] = self._funding_result(store, 10, 3, persisted)
            results["clusters"] = self._clusters_result(
                store, minutes, 10, 3, persisted
            )
            if self.has_funding():
                results["provenance"] = self._provenance_result(
                    store, minutes, persisted
                )
            results["cluster_quality"] = self._cluster_quality_result(
                store, minutes, persisted
            )
            results["wallets"] = self._wallets_result(store, minutes, persisted)
            if roots:
                results["cohort"] = self._cohort_result(
                    store, minutes, roots, persisted
                )
            results["validation"] = self._validation_result(
                store, validate_workspace(store, self.launch), persisted
            )
            results["derived_validation"] = self._validation_result(
                store,
                validate_derived(
                    store,
                    minutes,
                    decimals=self.launch.decimals,
                    include_report=False,
                ),
                persisted,
                "analysis/derived-validation.json",
            )
            return RefreshResult(results)

    # ---- integrity and workspace -----------------------------------------

    def validate(self, *, persist: bool | None = None) -> ValidationResult:
        with self._analysis_scope(persist) as (store, persisted):
            return self._validation_result(
                store, validate_workspace(store, self.launch), persisted
            )

    def validate_derived(
        self, minutes: int = 30, *, persist: bool | None = None
    ) -> ValidationResult:
        with self._analysis_scope(persist, fallback_analysis=True) as (
            store,
            persisted,
        ):
            return self._validation_result(
                store,
                validate_derived(
                    store,
                    minutes,
                    decimals=self.launch.decimals,
                ),
                persisted,
                "analysis/derived-validation.json",
            )

    def compare(
        self,
        left_minutes: int,
        right_minutes: int,
        *,
        output: str | None = None,
        persist: bool | None = None,
    ) -> ComparisonResult:
        with self._analysis_scope(persist, fallback_analysis=True) as (
            store,
            persisted,
        ):
            data = compare_windows(
                store,
                self.launch,
                left_minutes=left_minutes,
                right_minutes=right_minutes,
                output=output,
            )
            destination = (
                output or f"analysis/comparison-{left_minutes}-{right_minutes}.json"
            )
            artifacts = (
                (store.path(destination),)
                if persisted and store.path(destination).exists()
                else ()
            )
            return ComparisonResult(data, {}, artifacts)

    def manifest(self) -> dict[str, Any]:
        return self.store.write_manifest()
