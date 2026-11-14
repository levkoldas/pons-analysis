"""Load and shape report artifacts from the workspace store.

The report itself is a pure renderer: every value comes from existing
``analysis/`` documents. This module owns those reads (plus source hashing)
so section renderers stay free of I/O.
"""

import hashlib
from collections.abc import Iterable
from typing import Any

from pons_analysis.core.constants import REPORT_SCHEMA_VERSION as SCHEMA_VERSION
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def read_json_artifact(store: ArtifactStore, relative: str, hint: str) -> Any:
    payload = store.read_json(relative)
    if payload is None:
        raise InvariantError(f"Missing report artifact {relative}; run {hint}")
    if not isinstance(payload, dict):
        raise InvariantError(f"Malformed report artifact {relative}; run {hint}")
    return payload


def read_csv_artifact(
    store: ArtifactStore, relative: str, hint: str, *, required: bool = True
) -> list[dict[str, str]]:
    if required and not store.exists(relative):
        raise InvariantError(f"Missing report artifact {relative}; run {hint}")
    return store.read_csv(relative)


def _reject_markup(value: Any, path: str = "report") -> None:
    if isinstance(value, str):
        if "<" in value or ">" in value:
            raise InvariantError(f"Report data contains HTML markup at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_markup(item, f"{path}/{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_markup(item, f"{path}/{index}")


def as_int(value: str | int | None, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def as_float(value: str | float | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def hash_source(
    store: ArtifactStore, relative: str, sources: dict[str, dict[str, Any]]
) -> None:
    path = store.path(relative)
    if not path.exists():
        raise InvariantError(f"Missing report source {relative}")
    payload = path.read_bytes()
    sources[relative] = {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def top_positions(
    rows: Iterable[dict[str, str]], limit: int = 10
) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        parsed.append(
            {
                "wallet": row["wallet"],
                "cohort": row.get("cohort") == "True",
                "tokens_end": as_float(row.get("tokens_end")),
                "realized_quote_eth": as_float(row.get("realized_quote_eth")),
                "unrealized_quote_eth": as_float(row.get("unrealized_quote_eth")),
                "gas_quote_eth": as_float(row.get("gas_quote_eth")),
                "net_quote_eth": as_float(row.get("net_quote_eth")),
                "net_quote_raw": as_int(row.get("net_quote_raw")),
                "net_roi_bps": (
                    as_int(row.get("net_roi_bps"))
                    if row.get("net_roi_bps") not in (None, "")
                    else None
                ),
                "holding_seconds": (
                    as_int(row.get("holding_seconds"))
                    if row.get("holding_seconds") not in (None, "")
                    else None
                ),
            }
        )
    parsed.sort(key=lambda row: (-row["net_quote_raw"], row["wallet"]))
    return parsed[:limit]


def top_holders(
    rows: Iterable[dict[str, str]], limit: int = 10
) -> list[dict[str, Any]]:
    parsed = [
        {
            "wallet": row["wallet"],
            "tokens_raw": as_int(row.get("tokens_raw")),
            "tokens": as_float(row.get("tokens")),
            "pct": as_float(row.get("pct")),
        }
        for row in rows
    ]
    parsed.sort(key=lambda row: (-row["tokens_raw"], row["wallet"]))
    return parsed[:limit]


def top_rotations(
    rows: Iterable[dict[str, str]], limit: int = 10
) -> list[dict[str, Any]]:
    parsed = [
        {
            "source": row["source_wallet"],
            "destination": row["destination_wallet"],
            "seconds": as_float(row.get("seconds_after_migration")),
            "volume_raw": as_int(row.get("volume_raw")),
            "volume_eth": as_float(row.get("volume_eth")),
            "tokens": as_float(row.get("input_tokens")),
        }
        for row in rows
    ]
    parsed.sort(key=lambda row: (-row["volume_raw"], row["source"], row["destination"]))
    return parsed[:limit]


def sample_series(
    rows: Iterable[dict[str, str]], limit: int = 180
) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        price = as_float(row.get("price_eth"))
        if price is None:
            continue
        parsed.append(
            {
                "sequence": as_int(row.get("sequence")),
                "utc": row.get("utc", ""),
                "phase": row.get("phase", ""),
                "price_eth": price,
                "quote_amount": as_float(row.get("quote_amount")) or 0.0,
                "cumulative_volume_eth": as_float(row.get("cumulative_volume_eth")),
            }
        )
    if len(parsed) > limit:
        step = (len(parsed) - 1) / (limit - 1)
        parsed = [parsed[round(index * step)] for index in range(limit)]
    return parsed


def candle_series(rows: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        open_price = as_float(row.get("open_price_eth"))
        high = as_float(row.get("high_price_eth"))
        low = as_float(row.get("low_price_eth"))
        close = as_float(row.get("close_price_eth"))
        if None in (open_price, high, low, close):
            continue
        parsed.append(
            {
                "start_utc": row.get("start_utc", ""),
                "open_price_eth": open_price,
                "high_price_eth": high,
                "low_price_eth": low,
                "close_price_eth": close,
                "volume_eth": as_float(row.get("volume_eth")) or 0.0,
            }
        )
    return parsed


def holder_series(rows: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        holders = as_float(row.get("holders"))
        if holders is None:
            continue
        parsed.append(
            {
                "start_utc": row.get("start_utc", ""),
                "holders": int(holders),
                "top1_bps": as_float(row.get("top1_bps")),
                "top10_bps": as_float(row.get("top10_bps")),
                "hhi_bps": as_float(row.get("hhi_bps")),
            }
        )
    return parsed


def flow_series(rows: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = []
    for row in rows:
        net = as_float(row.get("net_flow_eth"))
        if net is None:
            continue
        parsed.append(
            {
                "start_utc": row.get("start_utc", ""),
                "net_flow_eth": net,
                "volume_eth": as_float(row.get("volume_eth")) or 0.0,
                "flow_imbalance_bps": as_float(row.get("flow_imbalance_bps")),
            }
        )
    return parsed


def load_report_data(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    cohort: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Read every report artifact and return the report data plus source hashes."""
    roots = tuple(sorted({addr(item) for item in cohort}))
    sources: dict[str, dict[str, Any]] = {}

    def read_json(relative: str, hint: str) -> Any:
        data = read_json_artifact(store, relative, hint)
        hash_source(store, relative, sources)
        return data

    def read_csv(relative: str, hint: str, *, required: bool = True):
        rows = read_csv_artifact(store, relative, hint, required=required)
        if required or store.exists(relative):
            hash_source(store, relative, sources)
        return rows

    expected_end = profile.start_timestamp + minutes * 60

    def require_period(label: str, summary: dict[str, Any]) -> None:
        if (
            summary.get("start_timestamp") != profile.start_timestamp
            or summary.get("end_timestamp_exclusive") != expected_end
        ):
            raise InvariantError(
                f"{label} artifacts have a different period; re-run the analysis"
            )

    def require_period_end(label: str, summary: dict[str, Any]) -> None:
        if summary.get("period_end_exclusive") != expected_end:
            raise InvariantError(
                f"{label} artifacts have a different period; re-run the analysis"
            )

    launch_summary = read_json("analysis/launch/summary.json", "analyze launch")
    launch_holders = read_csv("analysis/launch/holders.csv", "analyze launch")
    if len(launch_holders) != launch_summary.get("holders"):
        raise InvariantError(
            "Launch summary and holders.csv disagree; re-run analyze launch"
        )
    window_summary = read_json(
        f"analysis/window-{minutes}/summary.json",
        f"analyze window {minutes}",
    )
    rotations = read_csv(
        f"analysis/window-{minutes}/rotations.csv",
        f"analyze window {minutes}",
        required=False,
    )
    require_period("Window", window_summary)
    positions_summary = read_json(
        f"analysis/positions-{minutes}/summary.json",
        f"analyze positions {minutes}",
    )
    if positions_summary.get("minutes") != minutes:
        raise InvariantError(
            "Position artifacts have a different window; re-run analyze positions"
        )
    require_period("Position", positions_summary)
    position_rows = read_csv(
        f"analysis/positions-{minutes}/positions.csv",
        f"analyze positions {minutes}",
    )
    if len(position_rows) != positions_summary.get("wallets"):
        raise InvariantError(
            "Position summary and positions.csv disagree; re-run analyze positions"
        )
    route_performance = None
    route_path = f"analysis/route-performance-{minutes}/summary.json"
    if store.exists(route_path):
        route_performance = read_json(
            route_path, f"analyze route-performance {minutes}"
        )
        if route_performance.get("minutes") != minutes:
            raise InvariantError(
                "Route-performance artifacts have a different window; "
                "re-run analyze route-performance"
            )
    trajectory_summary = read_json(
        f"analysis/trajectory-{minutes}/summary.json",
        f"analyze trajectory {minutes}",
    )
    if trajectory_summary.get("minutes") != minutes:
        raise InvariantError(
            "Trajectory artifacts have a different window; re-run analyze trajectory"
        )
    require_period("Trajectory", trajectory_summary)
    trajectory_rows = read_csv(
        f"analysis/trajectory-{minutes}/trajectory.csv",
        f"analyze trajectory {minutes}",
    )
    if len(trajectory_rows) != trajectory_summary.get("trades"):
        raise InvariantError(
            "Trajectory summary and trajectory.csv disagree; re-run analyze trajectory"
        )
    candles_summary = None
    candle_rows: list[dict[str, str]] = []
    candles_path = f"analysis/candles-{minutes}/summary.json"
    if store.exists(candles_path):
        candles_summary = read_json(candles_path, f"analyze candles {minutes}")
        if candles_summary.get("minutes") != minutes:
            raise InvariantError(
                "Candle artifacts have a different window; re-run analyze candles"
            )
        require_period_end("Candle", candles_summary)
        candle_rows = read_csv(
            f"analysis/candles-{minutes}/candles.csv",
            f"analyze candles {minutes}",
        )
        profile_rows = read_csv(
            f"analysis/candles-{minutes}/volume_profile.csv",
            f"analyze candles {minutes}",
        )
        if len(candle_rows) != candles_summary.get("candles"):
            raise InvariantError(
                "Candle summary and candles.csv disagree; re-run analyze candles"
            )
        if len(profile_rows) != candles_summary.get("volume_profile_bins"):
            raise InvariantError(
                "Candle summary and volume_profile.csv disagree; re-run analyze candles"
            )
    holders_summary = None
    holder_rows: list[dict[str, str]] = []
    holders_path = f"analysis/holders-{minutes}/summary.json"
    if store.exists(holders_path):
        holders_summary = read_json(holders_path, f"analyze holders {minutes}")
        if holders_summary.get("minutes") != minutes:
            raise InvariantError(
                "Holder artifacts have a different window; re-run analyze holders"
            )
        require_period_end("Holder", holders_summary)
        holder_rows = read_csv(
            f"analysis/holders-{minutes}/timeline.csv",
            f"analyze holders {minutes}",
        )
        if len(holder_rows) != holders_summary.get("buckets"):
            raise InvariantError(
                "Holder summary and timeline.csv disagree; re-run analyze holders"
            )
    flow_summary = None
    flow_rows: list[dict[str, str]] = []
    flow_path = f"analysis/flow-{minutes}/summary.json"
    if store.exists(flow_path):
        flow_summary = read_json(flow_path, f"analyze flow {minutes}")
        if flow_summary.get("minutes") != minutes:
            raise InvariantError(
                "Flow artifacts have a different window; re-run analyze flow"
            )
        require_period_end("Flow", flow_summary)
        flow_rows = read_csv(
            f"analysis/flow-{minutes}/buckets.csv",
            f"analyze flow {minutes}",
        )
        read_csv(
            f"analysis/flow-{minutes}/wallets.csv",
            f"analyze flow {minutes}",
        )
        if len(flow_rows) != flow_summary.get("buckets"):
            raise InvariantError(
                "Flow summary and buckets.csv disagree; re-run analyze flow"
            )
    provenance_summary = None
    provenance_path = f"analysis/provenance-{minutes}/summary.json"
    if store.exists(provenance_path):
        provenance_summary = read_json(provenance_path, f"analyze provenance {minutes}")
        if provenance_summary.get("minutes") != minutes:
            raise InvariantError(
                "Provenance artifacts have a different window; "
                "re-run analyze provenance"
            )
        provenance_rows = read_csv(
            f"analysis/provenance-{minutes}/wallets.csv",
            f"analyze provenance {minutes}",
        )
        if len(provenance_rows) != len(provenance_summary.get("rows") or []):
            raise InvariantError(
                "Provenance summary and wallets.csv disagree; re-run analyze provenance"
            )
    wallet_summary = None
    wallet_path = f"analysis/wallets-{minutes}/summary.json"
    if store.exists(wallet_path):
        wallet_summary = read_json(wallet_path, f"analyze wallets {minutes}")
        if wallet_summary.get("minutes") != minutes:
            raise InvariantError(
                "Wallet scorecard artifacts have a different window; "
                "re-run analyze wallets"
            )
        wallet_rows_csv = read_csv(
            f"analysis/wallets-{minutes}/wallets.csv",
            f"analyze wallets {minutes}",
        )
        if len(wallet_rows_csv) != wallet_summary.get("wallets"):
            raise InvariantError(
                "Wallet summary and wallets.csv disagree; re-run analyze wallets"
            )
    entry_cohort_summary = None
    entry_cohort_path = f"analysis/entry-cohorts-{minutes}/summary.json"
    if store.exists(entry_cohort_path):
        entry_cohort_summary = read_json(
            entry_cohort_path, f"analyze entry-cohorts {minutes}"
        )
        if entry_cohort_summary.get("minutes") != minutes:
            raise InvariantError(
                "Entry-cohort artifacts have a different window; "
                "re-run analyze entry-cohorts"
            )
        entry_cohort_rows = read_csv(
            f"analysis/entry-cohorts-{minutes}/cohorts.csv",
            f"analyze entry-cohorts {minutes}",
        )
        entry_wallet_rows = read_csv(
            f"analysis/entry-cohorts-{minutes}/wallets.csv",
            f"analyze entry-cohorts {minutes}",
        )
        if len(entry_cohort_rows) != entry_cohort_summary.get("cohorts"):
            raise InvariantError(
                "Entry-cohort summary and cohorts.csv disagree; "
                "re-run analyze entry-cohorts"
            )
        if len(entry_wallet_rows) != entry_cohort_summary.get("wallets"):
            raise InvariantError(
                "Entry-cohort summary and wallets.csv disagree; "
                "re-run analyze entry-cohorts"
            )
    retention_summary = None
    retention_path = f"analysis/retention-{minutes}/summary.json"
    if store.exists(retention_path):
        retention_summary = read_json(retention_path, f"analyze retention {minutes}")
        if retention_summary.get("minutes") != minutes:
            raise InvariantError(
                "Retention artifacts have a different window; re-run analyze retention"
            )
        require_period_end("Retention", retention_summary)
        retention_cohorts = read_csv(
            f"analysis/retention-{minutes}/cohorts.csv",
            f"analyze retention {minutes}",
        )
        retention_wallets = read_csv(
            f"analysis/retention-{minutes}/wallets.csv",
            f"analyze retention {minutes}",
        )
        read_csv(
            f"analysis/retention-{minutes}/timeline.csv",
            f"analyze retention {minutes}",
        )
        if len(retention_cohorts) != retention_summary.get("cohorts"):
            raise InvariantError(
                "Retention summary and cohorts.csv disagree; re-run analyze retention"
            )
        if len(retention_wallets) != retention_summary.get("wallets"):
            raise InvariantError(
                "Retention summary and wallets.csv disagree; re-run analyze retention"
            )
    cohort_summary = None
    if roots:
        cohort_summary = read_json(
            f"analysis/cohort-{minutes}/summary.json",
            f"analyze cohort {minutes} --cohort-file <file>",
        )
        if cohort_summary.get("minutes") != minutes:
            raise InvariantError(
                "Cohort artifacts have a different window; re-run analyze cohort"
            )
        require_period("Cohort", cohort_summary)
        cohort_generations = read_csv(
            f"analysis/cohort-{minutes}/generations.csv",
            f"analyze cohort {minutes} --cohort-file <file>",
        )
        observed_roots = {
            row["wallet"] for row in cohort_generations if row.get("generation") == "0"
        }
        if observed_roots != set(roots):
            raise InvariantError(
                f"Cohort artifacts for {minutes}m do not match the requested "
                "roots; re-run analyze cohort with the same cohort"
            )
    funding_summary = None
    funding_path = "analysis/funding/summary.json"
    if store.exists(funding_path):
        funding_summary = read_json(funding_path, "analyze funding")

    cluster_summary = None
    cluster_path = "analysis/clusters/summary.json"
    if store.exists(cluster_path):
        cluster_summary = read_json(cluster_path, f"analyze clusters {minutes}")
        if cluster_summary.get("minutes") != minutes:
            raise InvariantError(
                "Cluster artifacts have a different window; re-run analyze clusters"
            )
        cluster_rows_csv = read_csv(
            "analysis/clusters/clusters.csv",
            f"analyze clusters {minutes}",
        )
        round_trip_rows = read_csv(
            "analysis/clusters/round_trips.csv",
            f"analyze clusters {minutes}",
            required=False,
        )
        if cluster_summary.get("clusters") != len(cluster_rows_csv):
            raise InvariantError(
                "Cluster summary and clusters.csv disagree; re-run analyze clusters"
            )
        behavior = cluster_summary.get("behavior") or {}
        if behavior.get("round_trips") != len(round_trip_rows):
            raise InvariantError(
                "Cluster summary and round_trips.csv disagree; re-run analyze clusters"
            )

    cluster_quality_summary = None
    cluster_quality_path = f"analysis/cluster-quality-{minutes}/summary.json"
    if store.exists(cluster_quality_path):
        cluster_quality_summary = read_json(
            cluster_quality_path, f"analyze cluster-quality {minutes}"
        )
        if cluster_quality_summary.get("minutes") != minutes:
            raise InvariantError(
                "Cluster-quality artifacts have a different window; "
                "re-run analyze cluster-quality"
            )
        cluster_quality_rows = read_csv(
            f"analysis/cluster-quality-{minutes}/clusters.csv",
            f"analyze cluster-quality {minutes}",
        )
        if len(cluster_quality_rows) != len(cluster_quality_summary.get("rows") or []):
            raise InvariantError(
                "Cluster-quality summary and clusters.csv disagree; "
                "re-run analyze cluster-quality"
            )

    fees_summary = None
    fees_path = f"analysis/fees-{minutes}/summary.json"
    if store.exists(fees_path):
        fees_summary = read_json(fees_path, f"analyze fees {minutes}")
        if fees_summary.get("minutes") != minutes:
            raise InvariantError(
                "Fee artifacts have a different window; re-run analyze fees"
            )
        fee_wallets = read_csv(
            f"analysis/fees-{minutes}/wallets.csv",
            f"analyze fees {minutes}",
        )
        fee_groups = read_csv(
            f"analysis/fees-{minutes}/groups.csv",
            f"analyze fees {minutes}",
        )
        totals = fees_summary.get("totals") or {}
        if len(fee_groups) != len(fees_summary.get("groups") or []):
            raise InvariantError(
                "Fee summary and groups.csv disagree; re-run analyze fees"
            )
        if sum(int(row["trades"]) for row in fee_wallets) != totals.get("trades"):
            raise InvariantError("Fee wallets and totals disagree; re-run analyze fees")

    lifecycle_summary = None
    lifecycle_path = f"analysis/lifecycle-{minutes}/summary.json"
    if store.exists(lifecycle_path):
        lifecycle_summary = read_json(lifecycle_path, f"analyze lifecycle {minutes}")
        if lifecycle_summary.get("minutes") != minutes:
            raise InvariantError(
                "Lifecycle artifacts have a different window; re-run analyze lifecycle"
            )
        lifecycle_groups = read_csv(
            f"analysis/lifecycle-{minutes}/groups.csv",
            f"analyze lifecycle {minutes}",
        )
        lifecycle_wallets = read_csv(
            f"analysis/lifecycle-{minutes}/wallets.csv",
            f"analyze lifecycle {minutes}",
        )
        if len(lifecycle_groups) != len(lifecycle_summary.get("groups") or []):
            raise InvariantError(
                "Lifecycle summary and groups.csv disagree; re-run analyze lifecycle"
            )
        if len(lifecycle_wallets) != lifecycle_summary.get("wallets"):
            raise InvariantError(
                "Lifecycle summary and wallets.csv disagree; re-run analyze lifecycle"
            )
        if sum(
            int(row["wallets"]) for row in lifecycle_groups
        ) != lifecycle_summary.get("wallets"):
            raise InvariantError(
                "Lifecycle groups do not cover every wallet; re-run analyze lifecycle"
            )

    execution_summary = None
    execution_path = f"analysis/execution-{minutes}/summary.json"
    if store.exists(execution_path):
        execution_summary = read_json(execution_path, f"analyze execution {minutes}")
        if execution_summary.get("minutes") != minutes:
            raise InvariantError(
                "Execution artifacts have a different window; re-run analyze execution"
            )
        execution_groups = read_csv(
            f"analysis/execution-{minutes}/groups.csv",
            f"analyze execution {minutes}",
        )
        execution_wallets = read_csv(
            f"analysis/execution-{minutes}/wallets.csv",
            f"analyze execution {minutes}",
        )
        if len(execution_groups) != len(execution_summary.get("groups") or []):
            raise InvariantError(
                "Execution summary and groups.csv disagree; re-run analyze execution"
            )
        if len(execution_wallets) != execution_summary.get("wallets"):
            raise InvariantError(
                "Execution summary and wallets.csv disagree; re-run analyze execution"
            )

    def _metric_count(value: object, fallback: int) -> int:
        if isinstance(value, bool):
            return fallback
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
        return fallback

    quality = None
    raw_validation_path = "analysis/validation.json"
    derived_validation_path = "analysis/derived-validation.json"
    if store.exists(raw_validation_path) or store.exists(derived_validation_path):
        quality = {}
        if store.exists(raw_validation_path):
            raw_validation = read_json(raw_validation_path, "validate")
            raw_checks = raw_validation.get("checks")
            if not isinstance(raw_checks, list):
                raw_checks = []
            raw_checks = [check for check in raw_checks if isinstance(check, dict)]
            raw_failed = sum(not check.get("ok") for check in raw_checks)
            quality["raw"] = {
                "passed": bool(raw_validation.get("passed")),
                "checks": _metric_count(raw_validation.get("checks"), len(raw_checks)),
                "failures": _metric_count(raw_validation.get("failures"), raw_failed),
                "failed_checks": [
                    check.get("check", "")
                    for check in raw_checks
                    if not check.get("ok")
                ],
            }
        if store.exists(derived_validation_path):
            derived_validation = read_json(derived_validation_path, "validate-derived")
            if derived_validation.get("minutes") == minutes:
                derived_results = derived_validation.get("results")
                if not isinstance(derived_results, list):
                    derived_results = []
                derived_results = [
                    check for check in derived_results if isinstance(check, dict)
                ]
                derived_failed = sum(not check.get("ok") for check in derived_results)
                quality["derived"] = {
                    "passed": bool(derived_validation.get("passed")),
                    "checks": _metric_count(
                        derived_validation.get("checks"), len(derived_results)
                    ),
                    "failures": _metric_count(
                        derived_validation.get("failures"), derived_failed
                    ),
                    "failed_checks": [
                        check.get("name", "")
                        for check in derived_results
                        if not check.get("ok")
                    ],
                }

    data = {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "name": profile.name,
            "chain": profile.chain,
            "token": profile.token,
            "decimals": profile.decimals,
            "supply_raw": profile.supply,
        },
        "minutes": minutes,
        "period": {
            "start_timestamp": trajectory_summary.get("start_timestamp"),
            "end_timestamp_exclusive": trajectory_summary.get(
                "end_timestamp_exclusive"
            ),
            "start_utc": trajectory_summary.get("start_utc"),
            "end_utc": trajectory_summary.get("end_utc"),
        },
        "launch": {
            "summary": launch_summary,
            "top_holders": top_holders(launch_holders),
        },
        "window": {
            "summary": window_summary,
            "top_rotations": top_rotations(rotations),
        },
        "positions": {
            "summary": positions_summary,
            "top_wallets": top_positions(position_rows),
        },
        "route_performance": route_performance,
        "trajectory": {
            "summary": trajectory_summary,
            "series": sample_series(trajectory_rows),
        },
        "candles": (
            {
                "summary": candles_summary,
                "series": candle_series(candle_rows),
            }
            if candles_summary is not None
            else None
        ),
        "holders": (
            {
                "summary": holders_summary,
                "timeline": holder_series(holder_rows),
            }
            if holders_summary is not None
            else None
        ),
        "flow": (
            {
                "summary": flow_summary,
                "series": flow_series(flow_rows),
            }
            if flow_summary is not None
            else None
        ),
        "provenance": provenance_summary,
        "wallet_scorecard": wallet_summary,
        "entry_cohorts": entry_cohort_summary,
        "retention": retention_summary,
        "quality": quality,
        "cohort": cohort_summary,
        "lifecycle": lifecycle_summary,
        "execution": execution_summary,
        "cluster_quality": cluster_quality_summary,
        "clusters": cluster_summary,
        "fees": fees_summary,
        "funding": funding_summary,
        "sources": sources,
    }
    _reject_markup(data)
    _reject_markup(sources, "sources")
    return data, sources
