"""Wallet scorecard, cohort, retention, and cluster checks."""

import math
from typing import Any

from pons_analysis.validation.derived.context import (
    ValidationContext,
    require_summary,
)


def _row_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _ranking_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _optional_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return None if value in (None, "") else float(value)


def _same_float(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left == right
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)


def run_entry_cohorts(ctx: ValidationContext) -> None:
    cohorts = ctx.entry_cohorts
    entry_wallets = ctx.entry_wallets
    positions = ctx.positions
    entry_summary = ctx.summaries.get("entry-cohorts")
    require_summary(ctx, entry_summary, cohorts or entry_wallets, "entry-cohort")
    if entry_summary is not None:
        ctx.check(
            "entry cohort row count",
            entry_summary.get("cohorts") == len(cohorts),
            f"{entry_summary.get('cohorts')} != {len(cohorts)}",
        )
        ctx.check(
            "entry cohort wallet coverage",
            int(entry_summary.get("wallets") or 0)
            + int(entry_summary.get("unbucketable_wallets") or 0)
            == len(positions),
            "bucketable + unbucketable != positions",
        )
    if cohorts:
        bad_entry_net = [
            row["bucket"]
            for row in cohorts
            if row.get("net_quote_raw") not in (None, "")
            and int(row["net_quote_raw"])
            != int(row.get("realized_quote_raw") or 0)
            + int(row["unrealized_quote_raw"] or 0)
            - int(row.get("gas_quote_raw") or 0)
        ]
        ctx.check(
            "entry-cohort net identity",
            not bad_entry_net,
            ", ".join(bad_entry_net[:5]),
        )
        cohort_net_values = [_optional_float(row, "net_quote_eth") for row in cohorts]
        unbucketable_net = _optional_float(entry_summary, "unbucketable_net_quote_eth")
        position_net = _optional_float(ctx.position_totals, "net_quote_eth")
        entry_net_ok = (
            position_net is None
            and (
                any(value is None for value in cohort_net_values)
                or unbucketable_net is None
            )
        ) or (
            position_net is not None
            and all(value is not None for value in cohort_net_values)
            and unbucketable_net is not None
            and math.isclose(
                sum(value for value in cohort_net_values if value is not None)
                + unbucketable_net,
                position_net,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        )
        ctx.check(
            "entry-cohort net total",
            entry_net_ok,
            "bucketable + unbucketable net != positions net",
        )
        entry_position_by_wallet = {row["wallet"].lower(): row for row in positions}
        entry_wallet_mismatches = []
        for row in entry_wallets:
            position = entry_position_by_wallet.get(row["wallet"].lower())
            if position is None:
                continue
            if any(
                not _same_float(
                    _optional_float(row, key),
                    _optional_float(position, key),
                )
                for key in (
                    "realized_quote_eth",
                    "unrealized_quote_eth",
                    "gas_quote_eth",
                    "net_quote_eth",
                )
            ):
                entry_wallet_mismatches.append(row["wallet"])
        ctx.check(
            "entry-cohort wallet PnL rows",
            not entry_wallet_mismatches,
            ", ".join(entry_wallet_mismatches[:5]),
        )
        entry_rankings = {
            "top_by_net": (
                None,
                lambda row: (
                    -float(row.get("net_quote_eth") or 0),
                    int(row.get("bucket") or 0),
                ),
            ),
            "top_by_roi": (
                "roi_bps",
                lambda row: (
                    -float(row.get("roi_bps") or 0),
                    int(row.get("bucket") or 0),
                ),
            ),
            "top_by_wallets": (
                None,
                lambda row: (
                    -int(row.get("wallets") or 0),
                    int(row.get("bucket") or 0),
                ),
            ),
        }
        entry_ranking_mismatches = []
        for name, (field, key) in entry_rankings.items():
            eligible = (
                cohorts
                if field is None
                else [row for row in cohorts if row.get(field) not in (None, "")]
            )
            expected = [
                str(row.get("bucket")) for row in sorted(eligible, key=key)[:10]
            ]
            actual = [
                str(row.get("bucket")) for row in _ranking_rows(entry_summary.get(name))
            ]
            if actual != expected:
                entry_ranking_mismatches.append(name)
        ctx.check(
            "entry-cohort rankings",
            not entry_ranking_mismatches,
            ", ".join(entry_ranking_mismatches),
        )
        ctx.check(
            "entry-cohort coverage totals",
            sum(int(row.get("realized_quote_raw") or 0) for row in cohorts)
            + int(entry_summary.get("unbucketable_realized_quote_raw") or 0)
            == int(ctx.position_totals.get("realized_quote_raw") or 0)
            and sum(int(row.get("gas_quote_raw") or 0) for row in cohorts)
            + int(entry_summary.get("unbucketable_gas_quote_raw") or 0)
            == int(ctx.position_totals.get("gas_quote_raw") or 0)
            and sum(int(row.get("tokens_end_raw") or 0) for row in cohorts)
            + int(entry_summary.get("unbucketable_tokens_end_raw") or 0)
            == sum(int(row.get("tokens_end_raw") or 0) for row in positions)
            and (
                ctx.position_totals.get("unrealized_quote_raw") is None
                or sum(int(row.get("unrealized_quote_raw") or 0) for row in cohorts)
                + int(entry_summary.get("unbucketable_unrealized_quote_raw") or 0)
                == int(ctx.position_totals.get("unrealized_quote_raw") or 0)
            ),
            "bucketable + unbucketable coverage != positions",
        )


def run_retention(ctx: ValidationContext) -> None:
    retention_cohorts = ctx.retention_cohorts
    retention_wallets = ctx.retention_wallets
    retention_timeline = ctx.retention_timeline
    retention_summary = ctx.summaries.get("retention")
    require_summary(
        ctx,
        retention_summary,
        retention_cohorts or retention_wallets or retention_timeline,
        "retention",
    )
    if retention_summary is not None:
        ctx.check(
            "retention timeline consistency",
            bool(retention_timeline) == bool(retention_cohorts),
            "retention timeline and cohort tables disagree",
        )
        ctx.check(
            "retention cohort count",
            retention_summary.get("cohorts") == len(retention_cohorts),
            f"{retention_summary.get('cohorts')} != {len(retention_cohorts)}",
        )
        ctx.check(
            "retention wallet count",
            retention_summary.get("wallets") == len(retention_wallets),
            f"{retention_summary.get('wallets')} != {len(retention_wallets)}",
        )
    if retention_cohorts:
        ctx.check(
            "retention timeline present",
            bool(retention_timeline),
            "timeline.csv missing or empty",
        )
        expected_retention = [
            str(row.get("entry_bucket"))
            for row in sorted(
                retention_cohorts,
                key=lambda row: (
                    -int(row.get("token_retention_bps") or 0),
                    int(row.get("entry_bucket") or 0),
                ),
            )[:10]
        ]
        actual_retention = [
            str(row.get("entry_bucket"))
            for row in _ranking_rows(retention_summary.get("top_by_retention"))
        ]
        ctx.check(
            "retention ranking",
            actual_retention == expected_retention,
            "retention top list disagrees with cohorts",
        )


def run_provenance(ctx: ValidationContext) -> None:
    provenance = ctx.provenance
    provenance_summary = ctx.summaries.get("provenance")
    require_summary(ctx, provenance_summary, provenance, "provenance")
    if provenance_summary is not None:
        ctx.check(
            "provenance summary count",
            provenance_summary.get("wallets")
            == len(provenance)
            == _row_count(provenance_summary.get("rows")),
            f"{provenance_summary.get('wallets')} != {len(provenance)}",
        )
    if provenance:
        ctx.subset("provenance", provenance)
        provenance_positions = {row["wallet"].lower(): row for row in ctx.positions}
        provenance_mismatches = []
        for row in provenance:
            position = provenance_positions.get(row["wallet"].lower())
            if position is None:
                continue
            if not (
                _same_float(
                    _optional_float(row, "net_quote_eth"),
                    _optional_float(position, "net_quote_eth"),
                )
                and _same_float(
                    _optional_float(row, "tokens_end"),
                    _optional_float(position, "tokens_end"),
                )
            ):
                provenance_mismatches.append(row["wallet"])
        ctx.check(
            "provenance wallet positions",
            not provenance_mismatches,
            ", ".join(provenance_mismatches[:5]),
        )


def run_scorecard(ctx: ValidationContext) -> None:
    scorecard = ctx.scorecard
    positions = ctx.positions
    wallet_summary = ctx.summaries.get("wallets")
    require_summary(ctx, wallet_summary, scorecard, "wallet scorecard")
    if wallet_summary is not None:
        ctx.check(
            "wallet summary count",
            wallet_summary.get("wallets") == len(scorecard) == len(positions),
            f"{wallet_summary.get('wallets')} != {len(scorecard)} != {len(positions)}",
        )
    if scorecard:
        ctx.check(
            "wallet scorecard coverage",
            len(scorecard)
            == len(positions)
            == ctx.summaries.get("wallets", {}).get("wallets"),
            f"{len(scorecard)} scorecard vs {len(positions)} positions",
        )
        scorecard_net = ctx.summaries.get("wallets", {}).get("net_quote_eth")
        position_net = ctx.position_totals.get("net_quote_eth")
        ctx.check(
            "wallet scorecard net total",
            (
                (scorecard_net is None and position_net is None)
                or (
                    scorecard_net is not None
                    and position_net is not None
                    and math.isclose(
                        float(scorecard_net),
                        float(position_net),
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                )
            ),
            "scorecard net differs from positions",
        )
        positions_by_wallet = {row["wallet"].lower(): row for row in positions}
        scorecard_mismatches = []
        for row in scorecard:
            position = positions_by_wallet.get(row["wallet"].lower())
            if position is None:
                continue
            mismatch = False
            for key in (
                "realized_quote_eth",
                "unrealized_quote_eth",
                "gas_quote_eth",
                "net_quote_eth",
            ):
                left = None if row.get(key) in (None, "") else float(row[key])
                right = (
                    None if position.get(key) in (None, "") else float(position[key])
                )
                if left is None or right is None:
                    mismatch = left != right
                elif not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12):
                    mismatch = True
                if mismatch:
                    break
            if mismatch:
                scorecard_mismatches.append(row["wallet"])
        ctx.check(
            "wallet scorecard PnL rows",
            not scorecard_mismatches,
            ", ".join(scorecard_mismatches[:5]),
        )
        scorecard_ranking_specs = {
            "top_by_net": (
                None,
                lambda row: (
                    -float(row.get("net_quote_eth") or 0),
                    row.get("wallet", ""),
                ),
            ),
            "top_by_roi": (
                "net_roi_bps",
                lambda row: (
                    -float(row.get("net_roi_bps") or 0),
                    row.get("wallet", ""),
                ),
            ),
            "top_by_impact": (
                "execution_weighted_bps",
                lambda row: (
                    -float(row.get("execution_weighted_bps") or 0),
                    row.get("wallet", ""),
                ),
            ),
            "top_by_fees": (
                "total_fee_eth",
                lambda row: (
                    -float(row.get("total_fee_eth") or 0),
                    row.get("wallet", ""),
                ),
            ),
            "top_by_retention": (
                "token_retention_bps",
                lambda row: (
                    -float(row.get("token_retention_bps") or 0),
                    -float(row.get("net_quote_eth") or 0),
                    row.get("wallet", ""),
                ),
            ),
        }
        scorecard_ranking_mismatches = []
        for name, (field, key) in scorecard_ranking_specs.items():
            eligible = (
                scorecard
                if field is None
                else [row for row in scorecard if row.get(field) not in (None, "")]
            )
            expected = [row.get("wallet") for row in sorted(eligible, key=key)[:20]]
            actual = [
                row.get("wallet")
                for row in _ranking_rows(ctx.summaries.get("wallets", {}).get(name))
            ]
            if actual != expected:
                scorecard_ranking_mismatches.append(name)
        ctx.check(
            "wallet scorecard rankings",
            not scorecard_ranking_mismatches,
            ", ".join(scorecard_ranking_mismatches),
        )
        retention_wallets = ctx.retention_wallets
        if retention_wallets:
            retention_by_wallet = {
                row["wallet"].lower(): (
                    float(row["token_retention_bps"])
                    if row.get("token_retention_bps") not in (None, "")
                    else None
                )
                for row in retention_wallets
            }
            retention_mismatches = [
                row["wallet"]
                for row in scorecard
                if (
                    float(row["token_retention_bps"])
                    if row.get("token_retention_bps") not in (None, "")
                    else None
                )
                != retention_by_wallet.get(row["wallet"].lower())
            ]
            ctx.check(
                "scorecard retention join",
                not retention_mismatches,
                ", ".join(retention_mismatches[:5]),
            )


def run_cluster_quality(ctx: ValidationContext) -> None:
    quality = ctx.cluster_quality
    quality_summary = ctx.summaries.get("cluster-quality")
    clusters = ctx.clusters
    membership = [row for row in ctx.cluster_membership if row.get("cluster_id")]
    require_summary(ctx, quality_summary, quality, "cluster-quality")
    if quality_summary is not None:
        ctx.check(
            "cluster-quality row count",
            len(quality) == _row_count(quality_summary.get("rows")) == len(clusters),
            f"{len(quality)} quality vs {len(clusters)} clusters",
        )
        ctx.check(
            "cluster membership rows",
            bool(membership) == bool(quality),
            "cluster membership rows disagree with cluster-quality rows",
        )
    if quality:
        quality_summary = quality_summary or {}
        cluster_summary = ctx.json("analysis/clusters/summary.json") or {}
        ctx.check(
            "clusters window",
            cluster_summary.get("minutes") == ctx.minutes,
            f"{cluster_summary.get('minutes')} != {ctx.minutes}",
        )
        cluster_position_by_wallet = {
            row["wallet"].lower(): row for row in ctx.positions
        }
        cluster_wallet_mismatches = []
        for row in membership:
            position = cluster_position_by_wallet.get(row["wallet"].lower())
            if position is None:
                continue
            mismatch = False
            for key in (
                "realized_quote_raw",
                "unrealized_quote_raw",
                "gas_quote_raw",
                "net_quote_raw",
            ):
                left = None if row.get(key) in (None, "") else int(row[key])
                right = None if position.get(key) in (None, "") else int(position[key])
                if left != right:
                    mismatch = True
                    break
            if mismatch:
                cluster_wallet_mismatches.append(row["wallet"])
        ctx.check(
            "cluster wallet PnL rows",
            not cluster_wallet_mismatches,
            ", ".join(cluster_wallet_mismatches[:5]),
        )
        lifecycle_gas = ctx.lifecycle_gas
        membership_gas: dict[str, int] = {}
        for row in membership:
            cluster_id = row.get("cluster_id", "")
            if cluster_id:
                membership_gas[cluster_id] = membership_gas.get(cluster_id, 0) + (
                    lifecycle_gas.get(row.get("wallet", "").lower(), 0)
                )
        gas_mismatches = [
            row["cluster_id"]
            for row in quality
            if not math.isclose(
                float(row.get("gas_eth") or 0),
                membership_gas.get(row["cluster_id"], 0) / 10**18,
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        ]
        ctx.check(
            "cluster-quality gas",
            not gas_mismatches,
            ", ".join(gas_mismatches[:5]),
        )
        ctx.check(
            "cluster-quality gas total",
            math.isclose(
                float(quality_summary.get("gas_eth") or 0),
                sum(membership_gas.values()) / 10**18,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ),
            "summary gas != member lifecycle gas",
        )
        lifecycle = ctx.lifecycle
        if lifecycle:
            lifecycle_net: dict[str, float | None] = {
                row["wallet"].lower(): (
                    None
                    if row.get("net_quote_eth") in (None, "")
                    else float(row["net_quote_eth"])
                )
                for row in lifecycle
            }
            membership_net: dict[str, float | None] = {}
            for row in membership:
                cluster_id = row.get("cluster_id", "")
                if not cluster_id:
                    continue
                value = lifecycle_net.get(row.get("wallet", "").lower(), 0.0)
                current = membership_net.get(cluster_id, 0.0)
                if current is None or value is None:
                    membership_net[cluster_id] = None
                else:
                    membership_net[cluster_id] = current + value
            net_mismatches = []
            for row in quality:
                actual = (
                    None
                    if row.get("net_quote_eth") in (None, "")
                    else float(row["net_quote_eth"])
                )
                expected = membership_net.get(row["cluster_id"], 0.0)
                if actual is None or expected is None:
                    if actual != expected:
                        net_mismatches.append(row["cluster_id"])
                elif not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
                    net_mismatches.append(row["cluster_id"])
            ctx.check(
                "cluster-quality net",
                not net_mismatches,
                ", ".join(net_mismatches[:5]),
            )
        profit_known = all(
            row.get("profitable_wallets") not in (None, "")
            and row.get("losing_wallets") not in (None, "")
            for row in quality
        )
        expected_profit = (
            sum(int(row["profitable_wallets"]) for row in quality)
            if profit_known
            else None
        )
        expected_loss = (
            sum(int(row["losing_wallets"]) for row in quality) if profit_known else None
        )
        ctx.check(
            "cluster-quality profit counts",
            quality_summary.get("profitable_wallets") == expected_profit
            and quality_summary.get("losing_wallets") == expected_loss,
            "summary profit/loss counts disagree with rows",
        )
        bad_roi = [
            row["cluster_id"]
            for row in quality
            if row.get("roi_median_bps") not in (None, "")
            and not (
                int(row["roi_min_bps"])
                <= int(row["roi_median_bps"])
                <= int(row["roi_max_bps"])
            )
        ]
        ctx.check(
            "cluster-quality ROI bounds",
            not bad_roi,
            ", ".join(bad_roi[:5]),
        )
        cluster_rankings = {
            "top_by_execution": (
                "execution_weighted_bps",
                lambda row: (
                    -float(row.get("execution_weighted_bps") or 0),
                    -float(row.get("execution_volume_eth") or 0),
                    row.get("cluster_id", ""),
                ),
            ),
            "top_by_fees": (
                "fee_burden_bps",
                lambda row: (
                    -float(row.get("fee_burden_bps") or 0),
                    row.get("cluster_id", ""),
                ),
            ),
            "top_by_roi": (
                "roi_median_bps",
                lambda row: (
                    -float(row.get("roi_median_bps") or 0),
                    row.get("cluster_id", ""),
                ),
            ),
        }
        cluster_rank_mismatches = []
        for name, (field, key) in cluster_rankings.items():
            eligible = [row for row in quality if row.get(field) not in (None, "")]
            expected = [row.get("cluster_id") for row in sorted(eligible, key=key)[:10]]
            actual = [
                row.get("cluster_id")
                for row in _ranking_rows(quality_summary.get(name))
            ]
            if actual != expected:
                cluster_rank_mismatches.append(name)
        ctx.check(
            "cluster-quality rankings",
            not cluster_rank_mismatches,
            ", ".join(cluster_rank_mismatches),
        )


def run_cohort(ctx: ValidationContext) -> None:
    cohort_generations = ctx.cohort_generations
    cohort_summary = ctx.summaries.get("cohort")
    require_summary(ctx, cohort_summary, cohort_generations, "cohort")
    if cohort_summary is not None and cohort_generations:
        terminal_rows = [
            row for row in cohort_generations if row.get("terminal") == "True"
        ]
        terminal_value = sum(
            int(row.get("unrealized_quote_raw") or 0)
            + int(row.get("cost_basis_remaining_raw") or 0)
            for row in terminal_rows
        )
        terminal_value_raw = cohort_summary.get("terminal_value_raw")
        ctx.check(
            "cohort terminal value",
            (terminal_value_raw is None or terminal_value == int(terminal_value_raw))
            and sum(int(row.get("tokens_end_raw") or 0) for row in terminal_rows)
            == int(cohort_summary.get("terminal_tokens_raw") or 0),
            "cohort terminal value/tokens disagree with generations",
        )
        net = cohort_summary.get("net_quote_raw")
        ctx.check(
            "cohort net identity",
            net is None
            or int(net)
            == int(cohort_summary.get("realized_quote_raw") or 0)
            + int(cohort_summary.get("unrealized_quote_raw") or 0)
            - int(cohort_summary.get("gas_quote_raw") or 0),
            "cohort net != realized + unrealized - gas",
        )
