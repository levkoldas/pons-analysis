from pons_analysis.storage.store import ArtifactStore
from pons_analysis.validation.derived import validate_derived
from pons_analysis.validation.derived.checks.fees import run as run_fees
from pons_analysis.validation.derived.checks.funding import run as run_funding
from pons_analysis.validation.derived.checks.market import (
    run_execution,
    run_holders,
    run_lifecycle,
    run_window,
)
from pons_analysis.validation.derived.checks.positions import (
    run as run_positions,
)
from pons_analysis.validation.derived.checks.routes import run as run_routes
from pons_analysis.validation.derived.checks.wallets import (
    _ranking_rows,
    _row_count,
    _same_float,
    run_cluster_quality,
    run_cohort,
    run_entry_cohorts,
    run_retention,
)
from pons_analysis.validation.derived.context import ValidationContext


def test_malformed_summary_is_a_failed_check_not_an_exception(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    path = store.path("analysis/positions-30/summary.json")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    result = validate_derived(store, 30)
    assert result["passed"] is False
    assert any(
        "analysis/positions-30/summary.json JSON" in item["name"]
        for item in result["failures"]
    )


def test_validation_discovers_custom_report_bundle(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    payload = {
        "schema_version": 37,
        "sources": {},
        "artifacts": {
            "html": "analysis/custom.html",
            "json": "analysis/custom.json",
        },
    }
    store.write_json("analysis/custom.json", payload)
    store.write_bytes("analysis/custom.html", b"<html></html>")
    assert ValidationContext(store, 30).report == payload
    assert ValidationContext(store, 30, include_report=False).report is None
    store.write_json(
        "analysis/bad-report.json",
        {"schema_version": 37, "sources": [], "artifacts": {}},
    )
    assert ValidationContext(store, 30).report == payload


def test_raw_validation_reports_invalid_funding_directory(tmp_path) -> None:
    from pons_analysis import MigrationCut, Pons
    from pons_analysis.validation.raw import validate_workspace

    store = ArtifactStore(tmp_path)
    store.write_json("evidence/funding/wallets/not-an-address/meta.json", {})
    profile = Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    result = validate_workspace(store, profile)
    assert any(
        item["check"] == "funding.not-an-address.name" and not item["ok"]
        for item in result["checks"]
    )


def test_validate_derived_defaults_to_report_checks(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json(
        "analysis/custom.json",
        {
            "schema_version": 37,
            "sources": {},
            "artifacts": {
                "html": "analysis/custom.html",
                "json": "analysis/custom.json",
            },
        },
    )
    store.write_bytes("analysis/custom.html", b"<html></html>")
    result = validate_derived(store, 30)
    assert any(item["name"] == "report schema" for item in result["results"])
    assert any(item["name"] == "report HTML exists" for item in result["results"])


def test_window_rotation_uses_launch_decimals(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/window-30/rotations.csv",
        [
            {
                "source_wallet": "0x" + "11" * 20,
                "input_tokens_raw": 1_000_000,
                "received_tokens_raw": 2_000_000,
                "seconds_after_migration": 12,
            }
        ],
    )
    store.write_json(
        "analysis/window-30/summary.json",
        {
            "start_timestamp": 0,
            "end_timestamp_exclusive": 1800,
            "rotation_count": 1,
            "rotating_original_wallets": 1,
            "rotated_tokens": 1.0,
            "rotation_received_tokens": 2.0,
            "rotation_first_seconds": 12,
            "rotation_last_seconds": 12,
        },
    )
    ctx = ValidationContext(store, 30, decimals=6)
    run_window(ctx)
    assert all(item["ok"] for item in ctx.checks), [
        item for item in ctx.checks if not item["ok"]
    ]


def test_route_validation_reports_unknown_wallet_instead_of_crashing(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    known = "0x" + "11" * 20
    unknown = "0x" + "22" * 20
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": known,
                "net_quote_eth": 1,
                "realized_quote_eth": 1,
                "gas_quote_eth": 0,
                "unrealized_quote_eth": 0,
            }
        ],
    )
    store.write_csv(
        "analysis/route-performance-30/routes.csv",
        [
            {
                "route": "r",
                "selector": "s",
                "wallets": 1,
                "net_quote_eth": 1,
                "realized_quote_eth": 1,
                "gas_quote_eth": 0,
                "unrealized_quote_eth": 0,
                "retained_wallets": 0,
            }
        ],
    )
    store.write_csv(
        "analysis/route-performance-30/wallets.csv",
        [{"wallet": unknown, "route": "r", "selector": "s"}],
    )
    store.write_json(
        "analysis/route-performance-30/summary.json",
        {
            "minutes": 30,
            "routes": 1,
            "wallets": 1,
            "unassigned_net_quote_eth": 0,
            "unassigned_wallets": 0,
            "net_quote_eth": 1,
        },
    )
    ctx = ValidationContext(store, 30)
    run_routes(ctx)
    assert any(
        item["name"] == "route-performance wallets subset" and not item["ok"]
        for item in ctx.checks
    )


def test_cohort_validation_accepts_unknown_terminal_value(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/cohort-30/generations.csv",
        [
            {
                "wallet": "0x" + "11" * 20,
                "terminal": "True",
                "tokens_end_raw": 10,
                "unrealized_quote_raw": "",
                "cost_basis_remaining_raw": 100,
            }
        ],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["cohort"] = {
        "terminal_value_raw": None,
        "terminal_tokens_raw": 10,
        "net_quote_raw": None,
        "realized_quote_raw": 0,
        "unrealized_quote_raw": None,
        "gas_quote_raw": 0,
    }
    run_cohort(ctx)
    assert all(item["ok"] for item in ctx.checks)


def test_funding_validation_accepts_member_to_member_transfer(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    a = "0x" + "11" * 20
    b = "0x" + "22" * 20
    store.write_csv(
        "analysis/funding/edges.csv",
        [{"source": a, "destination": b, "value_raw": 10}],
    )
    store.write_csv(
        "analysis/funding/wallets.csv",
        [
            {"wallet": a, "inbound_raw": 0, "outbound_raw": 10, "net_raw": -10},
            {"wallet": b, "inbound_raw": 10, "outbound_raw": 0, "net_raw": 10},
        ],
    )
    store.write_json(
        "analysis/funding/summary.json",
        {
            "edges": 1,
            "wallets": 2,
            "flow": {
                "inflow_raw": 0,
                "outflow_raw": 0,
                "gas_raw": 0,
                "net_flow_raw": 0,
            },
        },
    )
    ctx = ValidationContext(store, 30)
    run_funding(ctx)
    assert all(item["ok"] for item in ctx.checks)


def test_raw_validation_rejects_wrong_window_duration(tmp_path) -> None:
    from pons_analysis import MigrationCut, Pons
    from pons_analysis.validation.raw import validate_workspace

    store = ArtifactStore(tmp_path)
    store.write_json(
        "evidence/windows/30/bounds.json",
        {
            "start_timestamp": 100,
            "end_timestamp_exclusive": 5500,
            "start_block": 1,
            "end_block": 2,
            "end_block_timestamp": 5499,
            "next_block_timestamp": 5500,
        },
    )
    profile = Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=1,
        start_timestamp=100,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    result = validate_workspace(store, profile)
    assert any(
        item["check"] == "window.30.duration" and not item["ok"]
        for item in result["checks"]
    )


def test_report_validation_handles_unsafe_paths(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json(
        "analysis/custom.json",
        {
            "schema_version": 37,
            "sources": {"../outside": {"bytes": 1, "sha256": "0" * 64}},
            "artifacts": {"html": "/tmp/outside.html", "json": "analysis/custom.json"},
        },
    )
    result = validate_derived(store, 30)
    assert result["passed"] is False
    names = {item["name"] for item in result["failures"]}
    assert "report sources exist" in names
    assert "report HTML exists" in names


def test_validation_ranking_helper_ignores_null_summaries() -> None:
    assert _ranking_rows(None) == []
    assert _ranking_rows({"not": "a list"}) == []
    assert _ranking_rows([{"bucket": 1}, "bad"]) == [{"bucket": 1}]


def test_holder_validation_accepts_empty_concentration(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/holders-30/timeline.csv",
        [
            {
                "bucket": 0,
                "holders": 0,
                "new_holders": 0,
                "exited_holders": 0,
                "top10_bps": "",
                "hhi_bps": "",
                "transfers": 0,
            }
        ],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["holders"] = {
        "buckets": 1,
        "first_holders": 0,
        "last_holders": 0,
        "last_top10_bps": None,
        "last_hhi_bps": None,
        "peak_holders": 0,
        "new_holders": 0,
        "exited_holders": 0,
        "transfers": 0,
    }
    run_holders(ctx)
    assert all(item["ok"] for item in ctx.checks)


def test_lifecycle_validation_does_not_treat_unknown_as_zero(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "realized_quote_eth": "0",
                "unrealized_quote_eth": "0",
                "gas_quote_eth": "0",
                "net_quote_eth": "0",
            }
        ],
    )
    store.write_json(
        "analysis/positions-30/summary.json",
        {"totals": {"gas_quote_raw": 0}},
    )
    store.write_csv(
        "analysis/lifecycle-30/wallets.csv",
        [
            {
                "wallet": wallet,
                "realized_quote_eth": "0",
                "unrealized_quote_eth": "0",
                "gas_quote_eth": "0",
                "net_quote_eth": "",
                "gas_quote_raw": "0",
            }
        ],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["lifecycle"] = {
        "wallets": 1,
        "totals": {
            "realized_quote_raw": 0,
            "unrealized_quote_raw": 0,
            "net_quote_raw": None,
            "gas_quote_raw": 0,
        },
    }
    run_lifecycle(ctx)
    assert any(
        item["name"] == "lifecycle PnL rows" and not item["ok"] for item in ctx.checks
    )


def test_lot_extreme_validation_orders_indexes_numerically(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "gas_quote_raw": "0",
                "tokens_end_raw": "0",
                "cost_basis_remaining_raw": "0",
                "remaining_lots": "2",
                "median_lot_age_seconds": "10",
                "oldest_lot_age_seconds": "10",
                "unrealized_quote_raw": "0",
                "net_quote_raw": "0",
                "realized_quote_raw": "0",
            }
        ],
    )
    lots = [
        {
            "wallet": wallet,
            "lot_index": str(index),
            "acquired_timestamp": "990",
            "mark_value_raw": "0",
            "unrealized_pnl_raw": "0",
            "cost_raw": "0",
            "age_seconds": "10",
            "tokens_raw": "0",
        }
        for index in (9, 10)
    ]
    store.write_csv("analysis/positions-30/lots.csv", lots)
    store.write_json(
        "analysis/positions-30/summary.json",
        {
            "minutes": 30,
            "wallets": 1,
            "end_timestamp_exclusive": 1000,
            "inventory_age": {
                "remaining_lots": 2,
                "median_wallet_lot_age_seconds": 10,
                "oldest_lot_age_seconds": 10,
            },
            "inventory_age_buckets": [{"lots": 2, "tokens_raw": 0, "cost_raw": 0}],
            "lot_extremes": {
                "worst_unrealized": lots,
                "best_unrealized": lots,
            },
            "totals": {"gas_quote_raw": 0},
        },
    )
    ctx = ValidationContext(store, 30)
    ctx.load_summaries()
    run_positions(ctx)
    assert all(item["ok"] for item in ctx.checks)


def test_validation_number_comparison_distinguishes_unknown_and_zero() -> None:
    assert _same_float(None, None)
    assert _same_float(0.0, 0.0)
    assert not _same_float(None, 0.0)
    assert not _same_float(0.0, None)


def test_execution_validation_handles_null_counters(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/execution-30/wallets.csv",
        [{"wallet": "0x" + "11" * 20, "trades": "1", "volume_eth": "1"}],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["execution"] = {
        "wallets": 1,
        "attributed_trades": None,
        "unattributed_trades": 0,
        "impact_trades": 1,
    }
    run_execution(ctx)
    assert any(not item["ok"] for item in ctx.checks)


def test_validation_row_count_handles_null() -> None:
    assert _row_count(None) == 0
    assert _row_count({"not": "a list"}) == 0
    assert _row_count([1, 2]) == 2


def test_report_with_malformed_source_meta_is_validated(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json(
        "analysis/report.json",
        {
            "schema_version": 37,
            "sources": {"analysis/launch/summary.json": None},
            "artifacts": {
                "html": "analysis/report.html",
                "json": "analysis/report.json",
            },
        },
    )
    store.write_bytes("analysis/report.html", b"<html></html>")
    result = validate_derived(store, 30)
    assert any(
        item["name"] == "report sources exist" and not item["ok"]
        for item in result["results"]
    )


def test_malformed_report_json_is_a_failed_check(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.path("analysis/report.json").parent.mkdir(parents=True)
    store.path("analysis/report.json").write_text("{bad", encoding="utf-8")
    result = validate_derived(store, 30)
    assert result["passed"] is False
    assert any(
        item["name"] == "analysis/report.json JSON" and not item["ok"]
        for item in result["results"]
    )


def test_cluster_validation_rejects_wrong_window(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json("analysis/clusters/summary.json", {"minutes": 60, "clusters": 1})
    store.write_csv(
        "analysis/clusters/clusters.csv", [{"cluster_id": "c1", "wallets": 1}]
    )
    store.write_csv("analysis/cluster-quality-30/clusters.csv", [{"cluster_id": "c1"}])
    ctx = ValidationContext(store, 30)
    ctx.summaries["cluster-quality"] = {"minutes": 30, "rows": [{}]}
    run_cluster_quality(ctx)
    assert any(
        item["name"] == "clusters window" and not item["ok"] for item in ctx.checks
    )


def test_fee_validation_handles_null_totals(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/fees-30/wallets.csv",
        [{"wallet": "0x" + "11" * 20, "trades": "1"}],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["fees"] = {"minutes": 30, "totals": None}
    run_fees(ctx)
    assert any(not item["ok"] for item in ctx.checks)


def test_window_validation_rejects_wrong_period(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/window-30/rotations.csv",
        [{"source_wallet": "0x" + "11" * 20}],
    )
    store.write_json(
        "analysis/window-30/summary.json",
        {"start_timestamp": 0, "end_timestamp_exclusive": 3600},
    )
    ctx = ValidationContext(store, 30)
    run_window(ctx)
    assert any(
        item["name"] == "window period" and not item["ok"] for item in ctx.checks
    )


def test_non_object_report_json_is_a_failed_check(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json("analysis/report.json", [])
    result = validate_derived(store, 30)
    assert result["passed"] is False
    assert any(
        item["name"] == "analysis/report.json JSON" and not item["ok"]
        for item in result["results"]
    )


def test_holder_validation_rejects_unknown_as_zero(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/holders-30/timeline.csv",
        [
            {
                "bucket": 0,
                "holders": 10,
                "new_holders": 0,
                "exited_holders": 0,
                "top10_bps": "",
                "hhi_bps": "",
                "transfers": 0,
            }
        ],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["holders"] = {
        "buckets": 1,
        "first_holders": 10,
        "last_holders": 10,
        "last_top10_bps": 0,
        "last_hhi_bps": 0,
        "peak_holders": 10,
        "new_holders": 0,
        "exited_holders": 0,
        "transfers": 0,
    }
    run_holders(ctx)
    assert any(
        item["name"] == "holder summary endpoints" and not item["ok"]
        for item in ctx.checks
    )


def test_position_validation_accepts_no_remaining_lots(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "gas_quote_raw": "0",
                "tokens_end_raw": "0",
                "cost_basis_remaining_raw": "0",
                "remaining_lots": "0",
                "median_lot_age_seconds": "",
                "oldest_lot_age_seconds": "",
                "unrealized_quote_raw": "0",
                "net_quote_raw": "0",
                "realized_quote_raw": "0",
            }
        ],
    )
    store.write_csv("analysis/positions-30/lots.csv", [], fields=["wallet"])
    store.write_json(
        "analysis/positions-30/summary.json",
        {
            "minutes": 30,
            "wallets": 1,
            "end_timestamp_exclusive": 1000,
            "inventory_age": {
                "remaining_lots": 0,
                "median_wallet_lot_age_seconds": None,
                "oldest_lot_age_seconds": None,
            },
            "inventory_age_buckets": [],
            "lot_extremes": {"worst_unrealized": [], "best_unrealized": []},
            "totals": {"gas_quote_raw": 0},
        },
    )
    ctx = ValidationContext(store, 30)
    ctx.load_summaries()
    run_positions(ctx)
    assert all(item["ok"] for item in ctx.checks), [
        item for item in ctx.checks if not item["ok"]
    ]


def test_empty_funding_tables_must_have_zero_flow(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv("analysis/funding/edges.csv", [], fields=["source"])
    store.write_csv("analysis/funding/wallets.csv", [], fields=["wallet"])
    store.write_json(
        "analysis/funding/summary.json",
        {
            "edges": 0,
            "wallets": 0,
            "flow": {"gas_raw": 100, "net_flow_raw": 0},
        },
    )
    ctx = ValidationContext(store, 30)
    run_funding(ctx)
    assert any(
        item["name"] == "funding summary totals" and not item["ok"]
        for item in ctx.checks
    )


def test_derived_validation_does_not_require_window_artifacts(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "gas_quote_raw": "0",
                "tokens_end_raw": "0",
                "cost_basis_remaining_raw": "0",
                "remaining_lots": "0",
                "median_lot_age_seconds": "",
                "oldest_lot_age_seconds": "",
                "unrealized_quote_raw": "0",
                "net_quote_raw": "0",
                "realized_quote_raw": "0",
            }
        ],
    )
    store.write_csv("analysis/positions-30/lots.csv", [], fields=["wallet"])
    store.write_json(
        "analysis/positions-30/summary.json",
        {
            "minutes": 30,
            "wallets": 1,
            "end_timestamp_exclusive": 1000,
            "inventory_age": {
                "remaining_lots": 0,
                "median_wallet_lot_age_seconds": None,
                "oldest_lot_age_seconds": None,
            },
            "inventory_age_buckets": [],
            "lot_extremes": {"worst_unrealized": [], "best_unrealized": []},
            "totals": {"gas_quote_raw": 0},
        },
    )
    result = validate_derived(store, 30)
    assert result["passed"] is True
    assert not any(item["name"] == "window period" for item in result["results"])


def test_rows_without_summary_fail_validation(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/fees-30/wallets.csv",
        [{"wallet": "0x" + "11" * 20, "trades": "1"}],
    )
    ctx = ValidationContext(store, 30)
    run_fees(ctx)
    assert any(
        item["name"] == "fee summary present" and not item["ok"] for item in ctx.checks
    )


def test_empty_entry_cohorts_cover_positions(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [{"wallet": "0x" + "11" * 20}],
    )
    store.write_csv("analysis/entry-cohorts-30/cohorts.csv", [], fields=["bucket"])
    store.write_csv("analysis/entry-cohorts-30/wallets.csv", [], fields=["wallet"])
    ctx = ValidationContext(store, 30)
    ctx.summaries["entry-cohorts"] = {
        "minutes": 30,
        "cohorts": 0,
        "wallets": 0,
        "unbucketable_wallets": 0,
    }
    run_entry_cohorts(ctx)
    assert any(
        item["name"] == "entry cohort wallet coverage" and not item["ok"]
        for item in ctx.checks
    )


def test_empty_cluster_quality_requires_empty_membership(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/cluster-quality-30/clusters.csv", [], fields=["cluster_id"]
    )
    store.write_csv("analysis/clusters/clusters.csv", [], fields=["cluster_id"])
    store.write_csv(
        "analysis/clusters/wallets.csv",
        [{"wallet": "0x" + "11" * 20, "cluster_id": "c1"}],
    )
    ctx = ValidationContext(store, 30)
    ctx.summaries["cluster-quality"] = {"minutes": 30, "rows": []}
    run_cluster_quality(ctx)
    assert any(
        item["name"] == "cluster membership rows" and not item["ok"]
        for item in ctx.checks
    )


def test_retention_timeline_must_match_cohorts(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/retention-30/cohorts.csv",
        [{"entry_bucket": "60", "token_retention_bps": "0"}],
    )
    store.write_csv("analysis/retention-30/wallets.csv", [], fields=["wallet"])
    store.write_csv("analysis/retention-30/timeline.csv", [], fields=["entry_bucket"])
    ctx = ValidationContext(store, 30)
    ctx.summaries["retention"] = {"minutes": 30, "cohorts": 1, "wallets": 0}
    run_retention(ctx)
    assert any(
        item["name"] == "retention timeline consistency" and not item["ok"]
        for item in ctx.checks
    )


def test_fee_group_count_matches_summary(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv("analysis/fees-30/wallets.csv", [], fields=["wallet"])
    store.write_csv("analysis/fees-30/groups.csv", [], fields=["dimension"])
    ctx = ValidationContext(store, 30)
    ctx.summaries["fees"] = {
        "minutes": 30,
        "totals": {"trades": 0},
        "groups": [{"dimension": "all"}],
    }
    run_fees(ctx)
    assert any(
        item["name"] == "fee group count" and not item["ok"] for item in ctx.checks
    )
