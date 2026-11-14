"""Hierarchical, protocol-independent analytics."""

from pons_analysis.analytics.clusters.graph import analyze_clusters
from pons_analysis.analytics.clusters.quality import analyze_cluster_quality
from pons_analysis.analytics.cohorts.entry import analyze_entry_cohorts
from pons_analysis.analytics.cohorts.launch_to_exit import analyze_cohort
from pons_analysis.analytics.cohorts.lifecycle import analyze_lifecycle
from pons_analysis.analytics.cohorts.retention import analyze_retention
from pons_analysis.analytics.common.ethflow import (
    balance_history,
    flow_statement,
    reconcile_balances,
    wallet_balance_sheet,
)
from pons_analysis.analytics.common.rotations import detect_rotations
from pons_analysis.analytics.funding.graph import (
    analyze_funding,
    counterparties,
    native_edges,
)
from pons_analysis.analytics.funding.provenance import analyze_provenance
from pons_analysis.analytics.market.candles import analyze_candles
from pons_analysis.analytics.market.execution import analyze_execution
from pons_analysis.analytics.market.fees import (
    analyze_fees,
    creator_entitlement,
    escrow_balance,
    pool_fees,
)
from pons_analysis.analytics.market.flow import analyze_flow
from pons_analysis.analytics.market.holders import analyze_holders
from pons_analysis.analytics.market.launch import analyze_launch
from pons_analysis.analytics.market.trajectory import analyze_trajectory
from pons_analysis.analytics.market.window import analyze_window
from pons_analysis.analytics.positions import analyze_positions
from pons_analysis.analytics.routes.performance import analyze_route_performance
from pons_analysis.analytics.wallets.scorecard import analyze_wallets
from pons_analysis.core.accounting import (
    net_after_fees,
    net_cash_surplus,
    next_nonce_payment,
    reserve_exit_gross,
    v4_price,
    v4_virtual_reserves,
)

__all__ = [
    "analyze_candles",
    "analyze_cluster_quality",
    "analyze_clusters",
    "analyze_cohort",
    "analyze_entry_cohorts",
    "analyze_execution",
    "analyze_fees",
    "analyze_flow",
    "analyze_funding",
    "analyze_holders",
    "analyze_launch",
    "analyze_lifecycle",
    "analyze_positions",
    "analyze_provenance",
    "analyze_retention",
    "analyze_route_performance",
    "analyze_trajectory",
    "analyze_wallets",
    "analyze_window",
    "balance_history",
    "counterparties",
    "creator_entitlement",
    "detect_rotations",
    "escrow_balance",
    "flow_statement",
    "native_edges",
    "net_after_fees",
    "net_cash_surplus",
    "next_nonce_payment",
    "pool_fees",
    "reconcile_balances",
    "reserve_exit_gross",
    "v4_price",
    "v4_virtual_reserves",
    "wallet_balance_sheet",
]
