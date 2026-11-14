from pons_analysis.presentation.report.sections.evidence import (
    cluster_quality_section,
    execution_section,
    route_performance_section,
)
from pons_analysis.presentation.report.sections.overview import (
    _quality_label,
    cards_and_badges,
    launch_section,
    window_section,
)
from pons_analysis.presentation.report.sections.wallets import (
    cohort_section,
    wallet_pnl_section,
    wallet_scorecard_section,
)


def test_quality_card_omits_scopes_that_were_not_run() -> None:
    assert _quality_label({"derived": {"passed": True}}) == "derived yes"
    assert _quality_label({"raw": {"passed": False}}) == "raw no"
    assert _quality_label({}) == "not run"


def test_scorecard_section_handles_unknown_counts() -> None:
    html = wallet_scorecard_section(
        {
            "wallet_scorecard": {
                "wallets": 2,
                "profitable_wallets": None,
                "losing_wallets": None,
                "top_by_net": [],
                "top_by_retention": [],
            }
        }
    )
    assert "— profitable" in html
    assert "None profitable" not in html


def test_overview_cards_do_not_render_none_counts() -> None:
    cards, _ = cards_and_badges(
        {
            "trajectory": {"summary": {}},
            "positions": {"summary": {"totals": {}, "performance": {}}},
            "cohort": {"terminal_holders": None},
            "clusters": {"clusters": None, "behavior": {"round_trips": None}},
        },
        {},
    )
    assert "None" not in cards


def test_evidence_sections_handle_unknown_profit_counts() -> None:
    routes = route_performance_section(
        {
            "route_performance": {
                "top_by_net": [{"profitable_wallets": None, "losing_wallets": None}]
            }
        }
    )
    quality = cluster_quality_section(
        {
            "cluster_quality": {
                "profitable_wallets": None,
                "losing_wallets": None,
                "rows": [],
            }
        }
    )
    assert "None/None" not in routes
    assert "None profitable" not in quality


def test_wallet_pnl_section_handles_null_metrics() -> None:
    html = wallet_pnl_section(
        {
            "positions": {
                "summary": {
                    "totals": {},
                    "performance": {},
                    "inventory_age": {
                        "remaining_lots": 0,
                        "median_wallet_lot_age_seconds": None,
                        "oldest_lot_age_seconds": None,
                    },
                    "pnl_distribution": {
                        "profit_factor": None,
                        "profit_factor_unbounded": False,
                        "median_net_eth": -0.25,
                        "p10_net_eth": -1.0,
                        "p90_net_eth": -0.01,
                        "top10_profit_share_bps": None,
                        "histogram": [],
                    },
                    "lot_extremes": {},
                    "inventory_age_buckets": [],
                },
                "top_wallets": [],
            }
        }
    )
    assert "None" not in html


def test_overview_distinguishes_unavailable_reserve_replay() -> None:
    cards, _ = cards_and_badges(
        {
            "trajectory": {
                "summary": {"reserve_replay": {"available": False, "reconciled": None}}
            },
            "positions": {"summary": {}},
        },
        {},
    )
    assert "not reconciled" not in cards
    assert "n/a" in cards


def test_report_sections_accept_null_lists() -> None:
    assert launch_section(
        {"launch": {"summary": {"top_routes": None}, "top_holders": []}}
    )
    assert window_section(
        {"window": {"summary": {"direct_transfers": None}, "top_rotations": []}}
    )
    assert wallet_scorecard_section(
        {"wallet_scorecard": {"top_by_net": None, "top_by_retention": None}}
    )
    assert cohort_section(
        {"cohort": {"generation_rows": None, "top_terminal_holders": None}}
    )
    assert execution_section({"execution": {"groups": None, "top_by_weighted": None}})
    assert cluster_quality_section({"cluster_quality": {"rows": None}})
