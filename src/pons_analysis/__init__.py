"""A typed Python library for PONS launch and wallet analysis."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from pons_analysis._version import __version__

if TYPE_CHECKING:
    from pons_analysis.config import CachePolicy, RunConfig
    from pons_analysis.core.errors import (
        CacheMiss,
        ConfigurationError,
        IncompleteHistory,
        InvariantError,
        OptionalDependencyError,
        PonsError,
        ProviderError,
        ResolutionError,
        RetryableError,
        RpcError,
    )
    from pons_analysis.core.models import Launch, MigrationCut, PonsProtocol
    from pons_analysis.credentials import Credentials
    from pons_analysis.pons import Pons
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
    from pons_analysis.run import LaunchRun

_LAZY_IMPORTS = {
    "AnalysisResult": ("pons_analysis.results", "AnalysisResult"),
    "CacheMiss": ("pons_analysis.core.errors", "CacheMiss"),
    "CachePolicy": ("pons_analysis.config", "CachePolicy"),
    "CandlesResult": ("pons_analysis.results", "CandlesResult"),
    "ClusterQualityResult": ("pons_analysis.results", "ClusterQualityResult"),
    "ClustersResult": ("pons_analysis.results", "ClustersResult"),
    "CohortResult": ("pons_analysis.results", "CohortResult"),
    "ComparisonResult": ("pons_analysis.results", "ComparisonResult"),
    "ConfigurationError": ("pons_analysis.core.errors", "ConfigurationError"),
    "Credentials": ("pons_analysis.credentials", "Credentials"),
    "EntryCohortsResult": ("pons_analysis.results", "EntryCohortsResult"),
    "ExecutionResult": ("pons_analysis.results", "ExecutionResult"),
    "FeesResult": ("pons_analysis.results", "FeesResult"),
    "FlowResult": ("pons_analysis.results", "FlowResult"),
    "FundingResult": ("pons_analysis.results", "FundingResult"),
    "HoldersResult": ("pons_analysis.results", "HoldersResult"),
    "IncompleteHistory": ("pons_analysis.core.errors", "IncompleteHistory"),
    "InvariantError": ("pons_analysis.core.errors", "InvariantError"),
    "Launch": ("pons_analysis.core.models", "Launch"),
    "LaunchResult": ("pons_analysis.results", "LaunchResult"),
    "LaunchRun": ("pons_analysis.run", "LaunchRun"),
    "LifecycleResult": ("pons_analysis.results", "LifecycleResult"),
    "MigrationCut": ("pons_analysis.core.models", "MigrationCut"),
    "OptionalDependencyError": (
        "pons_analysis.core.errors",
        "OptionalDependencyError",
    ),
    "Pons": ("pons_analysis.pons", "Pons"),
    "PonsError": ("pons_analysis.core.errors", "PonsError"),
    "PonsProtocol": ("pons_analysis.core.models", "PonsProtocol"),
    "PositionsResult": ("pons_analysis.results", "PositionsResult"),
    "ProvenanceResult": ("pons_analysis.results", "ProvenanceResult"),
    "ProviderError": ("pons_analysis.core.errors", "ProviderError"),
    "RefreshResult": ("pons_analysis.results", "RefreshResult"),
    "ResolutionError": ("pons_analysis.core.errors", "ResolutionError"),
    "RetentionResult": ("pons_analysis.results", "RetentionResult"),
    "RetryableError": ("pons_analysis.core.errors", "RetryableError"),
    "RoutePerformanceResult": ("pons_analysis.results", "RoutePerformanceResult"),
    "RpcError": ("pons_analysis.core.errors", "RpcError"),
    "RunConfig": ("pons_analysis.config", "RunConfig"),
    "Table": ("pons_analysis.results", "Table"),
    "TrajectoryResult": ("pons_analysis.results", "TrajectoryResult"),
    "ValidationResult": ("pons_analysis.results", "ValidationResult"),
    "WalletsResult": ("pons_analysis.results", "WalletsResult"),
    "WindowResult": ("pons_analysis.results", "WindowResult"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "AnalysisResult",
    "CacheMiss",
    "CachePolicy",
    "CandlesResult",
    "ClusterQualityResult",
    "ClustersResult",
    "CohortResult",
    "ComparisonResult",
    "ConfigurationError",
    "Credentials",
    "EntryCohortsResult",
    "ExecutionResult",
    "FeesResult",
    "FlowResult",
    "FundingResult",
    "HoldersResult",
    "IncompleteHistory",
    "InvariantError",
    "Launch",
    "LaunchResult",
    "LaunchRun",
    "LifecycleResult",
    "MigrationCut",
    "OptionalDependencyError",
    "Pons",
    "PonsError",
    "PonsProtocol",
    "PositionsResult",
    "ProvenanceResult",
    "ProviderError",
    "RefreshResult",
    "ResolutionError",
    "RetentionResult",
    "RetryableError",
    "RoutePerformanceResult",
    "RpcError",
    "RunConfig",
    "Table",
    "TrajectoryResult",
    "ValidationResult",
    "WalletsResult",
    "WindowResult",
    "__version__",
]
