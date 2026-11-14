"""Typed, read-only analysis results and optional tabular integrations."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar

from pons_analysis import frames

if TYPE_CHECKING:
    from pons_analysis.ports import Store

Scalar = str | int | float | bool | None
_INT = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_FLOAT = re.compile(
    r"-?(?:[0-9]+\.[0-9]*(?:[eE][+-]?[0-9]+)?|"
    r"\.[0-9]+(?:[eE][+-]?[0-9]+)?|"
    r"[0-9]+[eE][+-]?[0-9]+)\Z"
)


def _typed(value: str | None) -> Scalar:
    if value is None or value == "":
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    if _INT.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        return float(value)
    return value


@dataclass(frozen=True, slots=True)
class Table:
    """Immutable columnar rows preserving exact Python integers."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping[str, Any]]) -> Table:
        if not rows:
            return cls((), ())
        columns: dict[str, None] = {}
        for row in rows:
            for column in row:
                columns.setdefault(column, None)
        order = tuple(columns)
        return cls(
            order,
            tuple(tuple(row.get(column) for column in order) for row in rows),
        )

    @classmethod
    def from_csv(cls, store: Store, relative: str | Path) -> Table:
        path = store.path(relative)
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                columns = tuple(reader.fieldnames or ())
                rows = tuple(
                    tuple(_typed(row.get(column, "")) for column in columns)
                    for row in reader
                )
        except FileNotFoundError:
            return cls((), ())
        return cls(columns, rows)

    def __len__(self) -> int:
        return len(self.rows)

    def column(self, name: str) -> tuple[Scalar, ...]:
        index = self.columns.index(name)
        return tuple(row[index] for row in self.rows)

    def to_dicts(self) -> list[dict[str, Scalar]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

    def to_polars(self) -> Any:
        return frames.to_polars(self)

    def to_arrow(self) -> Any:
        return frames.to_arrow(self)

    def to_pandas(self) -> Any:
        return frames.to_pandas(self)

    def to_numpy(self, columns: Sequence[str] | None = None) -> Any:
        return frames.to_numpy(self, columns)

    def to_duckdb(self) -> Any:
        return frames.to_duckdb(self)

    def to_networkx(
        self,
        *,
        source: str,
        target: str,
        edge_attributes: Sequence[str] | None = None,
        directed: bool = True,
    ) -> Any:
        return frames.to_networkx(
            self,
            source=source,
            target=target,
            edge_attributes=edge_attributes,
            directed=directed,
        )

    def to_parquet(self, path: str | Path) -> Path:
        return frames.to_parquet(self, path)


class AnalysisResult(Mapping[str, Any]):
    """Common result container; mapping access read through to the summary."""

    analysis: ClassVar[str] = "analysis"

    __slots__ = ("_summary", "artifacts", "tables")

    def __init__(
        self,
        summary: Mapping[str, Any],
        tables: Mapping[str, Table] | None = None,
        artifacts: Sequence[str | Path] = (),
    ):
        self._summary: Mapping[str, Any] = MappingProxyType(dict(summary))
        self.tables: Mapping[str, Table] = MappingProxyType(dict(tables or {}))
        self.artifacts = tuple(Path(path) for path in artifacts)

    @property
    def summary(self) -> Mapping[str, Any]:
        return self._summary

    def __getitem__(self, key: str) -> Any:
        return self._summary[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._summary)

    def __len__(self) -> int:
        return len(self._summary)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(analysis={self.analysis!r}, "
            f"tables={tuple(self.tables)!r}, rows={len(self)})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis,
            "summary": dict(self._summary),
            "tables": {name: table.to_dicts() for name, table in self.tables.items()},
            "artifacts": [str(path) for path in self.artifacts],
        }


class LaunchResult(AnalysisResult):
    analysis = "launch"

    @property
    def trades(self) -> Table:
        return self.tables["trades"]

    @property
    def transfers(self) -> Table:
        return self.tables["transfers"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]

    @property
    def holders(self) -> Table:
        return self.tables["holders"]

    @property
    def routes(self) -> Table:
        return self.tables["routes"]


class WindowResult(AnalysisResult):
    analysis = "window"

    @property
    def rotations(self) -> Table:
        return self.tables["rotations"]

    @property
    def original_wallets(self) -> Table:
        return self.tables["original_wallets"]

    @property
    def cohort_holdings_timeline(self) -> Table:
        return self.tables["cohort_holdings_timeline"]

    @property
    def five_minute_summary(self) -> Table:
        return self.tables["five_minute_summary"]


class PositionsResult(AnalysisResult):
    analysis = "positions"

    @property
    def positions(self) -> Table:
        return self.tables["positions"]

    @property
    def lots(self) -> Table:
        return self.tables["lots"]

    @property
    def trade_legs(self) -> Table:
        return self.tables["trade_legs"]

    @property
    def transactions(self) -> Table:
        return self.tables["transactions"]


class RoutePerformanceResult(AnalysisResult):
    analysis = "route_performance"

    @property
    def routes(self) -> Table:
        return self.tables["routes"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class WalletsResult(AnalysisResult):
    analysis = "wallets"

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class EntryCohortsResult(AnalysisResult):
    analysis = "entry_cohorts"

    @property
    def cohorts(self) -> Table:
        return self.tables["cohorts"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class RetentionResult(AnalysisResult):
    analysis = "retention"

    @property
    def cohorts(self) -> Table:
        return self.tables["cohorts"]

    @property
    def timeline(self) -> Table:
        return self.tables["timeline"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class LifecycleResult(AnalysisResult):
    analysis = "lifecycle"

    @property
    def groups(self) -> Table:
        return self.tables["groups"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class TrajectoryResult(AnalysisResult):
    analysis = "trajectory"

    @property
    def trajectory(self) -> Table:
        return self.tables["trajectory"]


class CandlesResult(AnalysisResult):
    analysis = "candles"

    @property
    def candles(self) -> Table:
        return self.tables["candles"]

    @property
    def volume_profile(self) -> Table:
        return self.tables["volume_profile"]


class FlowResult(AnalysisResult):
    analysis = "flow"

    @property
    def buckets(self) -> Table:
        return self.tables["buckets"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class HoldersResult(AnalysisResult):
    analysis = "holders"

    @property
    def timeline(self) -> Table:
        return self.tables["timeline"]


class ExecutionResult(AnalysisResult):
    analysis = "execution"

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]

    @property
    def groups(self) -> Table:
        return self.tables["groups"]


class CohortResult(AnalysisResult):
    analysis = "cohort"

    @property
    def generations(self) -> Table:
        return self.tables["generations"]

    @property
    def terminal_holders(self) -> Table:
        return self.tables["terminal_holders"]


class ClustersResult(AnalysisResult):
    analysis = "clusters"

    @property
    def clusters(self) -> Table:
        return self.tables["clusters"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]

    @property
    def edges(self) -> Table:
        return self.tables["edges"]

    @property
    def round_trips(self) -> Table:
        return self.tables["round_trips"]


class ClusterQualityResult(AnalysisResult):
    analysis = "cluster_quality"

    @property
    def clusters(self) -> Table:
        return self.tables["clusters"]


class FeesResult(AnalysisResult):
    analysis = "fees"

    @property
    def groups(self) -> Table:
        return self.tables["groups"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class FundingResult(AnalysisResult):
    analysis = "funding"

    @property
    def edges(self) -> Table:
        return self.tables["edges"]

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]

    @property
    def counterparties(self) -> Table:
        return self.tables["counterparties"]


class ProvenanceResult(AnalysisResult):
    analysis = "provenance"

    @property
    def wallets(self) -> Table:
        return self.tables["wallets"]


class ValidationResult(AnalysisResult):
    analysis = "validation"

    @property
    def passed(self) -> bool:
        return bool(self.summary.get("passed"))


class ComparisonResult(AnalysisResult):
    analysis = "comparison"


class RefreshResult(Mapping[str, AnalysisResult]):
    """Dependency-ordered full refresh result with named attributes."""

    __slots__ = ("_results",)

    def __init__(self, results: Mapping[str, AnalysisResult]):
        self._results: Mapping[str, AnalysisResult] = MappingProxyType(dict(results))

    def __getitem__(self, key: str) -> AnalysisResult:
        return self._results[key]

    def _get[ResultT: AnalysisResult](
        self, key: str, result_type: type[ResultT]
    ) -> ResultT:
        result = self._results[key]
        if not isinstance(result, result_type):
            raise TypeError(f"Result {key!r} is not a {result_type.__name__}")
        return result

    def __iter__(self) -> Iterator[str]:
        return iter(self._results)

    def __len__(self) -> int:
        return len(self._results)

    def as_dict(self) -> dict[str, Any]:
        return {name: result.as_dict() for name, result in self._results.items()}

    @property
    def launch(self) -> LaunchResult:
        return self._get("launch", LaunchResult)

    @property
    def window(self) -> WindowResult:
        return self._get("window", WindowResult)

    @property
    def positions(self) -> PositionsResult:
        return self._get("positions", PositionsResult)

    @property
    def route_performance(self) -> RoutePerformanceResult:
        return self._get("route_performance", RoutePerformanceResult)

    @property
    def lifecycle(self) -> LifecycleResult:
        return self._get("lifecycle", LifecycleResult)

    @property
    def entry_cohorts(self) -> EntryCohortsResult:
        return self._get("entry_cohorts", EntryCohortsResult)

    @property
    def retention(self) -> RetentionResult:
        return self._get("retention", RetentionResult)

    @property
    def trajectory(self) -> TrajectoryResult:
        return self._get("trajectory", TrajectoryResult)

    @property
    def candles(self) -> CandlesResult:
        return self._get("candles", CandlesResult)

    @property
    def flow(self) -> FlowResult:
        return self._get("flow", FlowResult)

    @property
    def holders(self) -> HoldersResult:
        return self._get("holders", HoldersResult)

    @property
    def execution(self) -> ExecutionResult:
        return self._get("execution", ExecutionResult)

    @property
    def fees(self) -> FeesResult:
        return self._get("fees", FeesResult)

    @property
    def clusters(self) -> ClustersResult:
        return self._get("clusters", ClustersResult)

    @property
    def cluster_quality(self) -> ClusterQualityResult:
        return self._get("cluster_quality", ClusterQualityResult)

    @property
    def wallets(self) -> WalletsResult:
        return self._get("wallets", WalletsResult)

    @property
    def validation(self) -> ValidationResult:
        return self._get("validation", ValidationResult)

    @property
    def derived_validation(self) -> ValidationResult:
        return self._get("derived_validation", ValidationResult)

    @property
    def funding(self) -> FundingResult | None:
        result = self._results.get("funding")
        return result if isinstance(result, FundingResult) else None

    @property
    def provenance(self) -> ProvenanceResult | None:
        result = self._results.get("provenance")
        return result if isinstance(result, ProvenanceResult) else None

    @property
    def cohort(self) -> CohortResult | None:
        result = self._results.get("cohort")
        return result if isinstance(result, CohortResult) else None
