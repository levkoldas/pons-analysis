"""Ordered set of derived-artifact check modules."""

from collections.abc import Callable

from pons_analysis.validation.derived.checks import (
    fees,
    funding,
    market,
    positions,
    report,
    routes,
    wallets,
)
from pons_analysis.validation.derived.context import ValidationContext

CHECK_SEQUENCE: tuple[Callable[[ValidationContext], None], ...] = (
    positions.run,
    fees.run,
    market.run_execution,
    market.run_lifecycle,
    market.run_trajectory,
    market.run_candles,
    market.run_holders,
    market.run_flow,
    wallets.run_entry_cohorts,
    wallets.run_retention,
    funding.run,
    wallets.run_provenance,
    wallets.run_scorecard,
    routes.run,
    wallets.run_cluster_quality,
    wallets.run_cohort,
    market.run_window,
    market.run_launch,
    report.run,
)

__all__ = ["CHECK_SEQUENCE"]
