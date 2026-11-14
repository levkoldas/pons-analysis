from pons_analysis import CachePolicy, MigrationCut, Pons, RunConfig
from pons_analysis.run import LaunchRun


def test_persisted_comparison_reports_its_artifact(tmp_path, monkeypatch) -> None:
    launch = Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=10,
        start_timestamp=1,
        migration=MigrationCut(block=10, tx_index=0, log_index=0),
    )
    run = LaunchRun(launch, tmp_path)

    def fake_compare(store, launch, *, left_minutes, right_minutes, output=None):
        destination = (
            output or f"analysis/comparison-{left_minutes}-{right_minutes}.json"
        )
        store.write_json(destination, {"left": left_minutes, "right": right_minutes})
        return {"left_minutes": left_minutes, "right_minutes": right_minutes}

    monkeypatch.setattr("pons_analysis.run.compare_windows", fake_compare)
    result = run.compare(30, 90, persist=True)
    assert len(result.artifacts) == 1
    assert result.artifacts[0].name == "comparison-30-90.json"
    assert result.artifacts[0].exists()
    run.close()


def test_successor_collection_preserves_zero_start_block(tmp_path, monkeypatch) -> None:
    launch = Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=10,
        start_timestamp=1,
        migration=MigrationCut(block=10, tx_index=0, log_index=0),
    )
    run = LaunchRun(launch, tmp_path)
    seen = {}

    def fake_collect(rpc, store, profile, *, start_block, wallets):
        seen["start_block"] = start_block
        return {}

    monkeypatch.setattr(
        "pons_analysis.run.successors_collection.collect_successors", fake_collect
    )
    run.collect_successors([], start_block=0, with_activity=False)
    assert seen["start_block"] == 0
    run.close()


def test_reusable_offline_window_returns_without_rpc(tmp_path) -> None:
    launch = Pons.launch(
        token="0x" + "11" * 20,
        supply=1,
        start_block=10,
        start_timestamp=100,
        migration=MigrationCut(block=10, tx_index=0, log_index=0),
    )
    run = LaunchRun(
        launch,
        tmp_path,
        config=RunConfig(cache=CachePolicy.OFFLINE),
    )
    directory = "evidence/windows/30"
    bounds = {
        "start_timestamp": 100,
        "end_timestamp_exclusive": 1900,
        "start_block": 10,
        "end_block": 20,
    }
    run.store.write_json(f"{directory}/bounds.json", bounds)
    run.store.write_json(f"{directory}/token_logs.json", [])
    run.store.write_json(f"{directory}/swaps_logs.json", [])
    run.store.write_json(f"{directory}/receipts.json", [])
    run.store.write_json(f"{directory}/blocks.json", [])
    assert run.collect_window(30) == bounds
    run.close()
