from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.cohorts.entry import analyze_entry_cohorts
from pons_analysis.analytics.cohorts.launch_to_exit import _edges
from pons_analysis.analytics.cohorts.retention import analyze_retention
from pons_analysis.core.models import RpcLog
from pons_analysis.storage.store import ArtifactStore


def _log(token, source, destination, index):
    return RpcLog(
        address=token,
        topics=[
            "0x" + "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            "0x" + "0" * 24 + source[2:].lower(),
            "0x" + "0" * 24 + destination[2:].lower(),
        ],
        data="0x" + "0" * 62 + "64",
        blockNumber=2,
        transactionHash="0x" + "aa" * 32,
        transactionIndex=0,
        logIndex=index,
    )


def test_retention_records_wallet_that_round_trips_in_one_bucket(tmp_path) -> None:
    token = "0x" + "22" * 20
    wallet_a = "0x" + "33" * 20
    wallet_b = "0x" + "44" * 20
    store = ArtifactStore(tmp_path)
    store.write_json("evidence/launch/transfers.json", [])
    store.write_json("evidence/launch/blocks.json", {})
    store.write_json(
        "evidence/windows/30/token_logs.json",
        [
            _log(token, "0x" + "00" * 20, wallet_a, 0).model_dump(
                mode="json", by_alias=True
            ),
            _log(token, wallet_a, wallet_b, 1).model_dump(mode="json", by_alias=True),
        ],
    )
    store.write_json("evidence/windows/30/blocks.json", {"2": {"timestamp": 1005}})
    profile = Pons.launch(
        token=token,
        supply=1000,
        start_block=1,
        start_timestamp=1000,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_retention(store, profile, minutes=30)
    assert summary["wallets"] == 2
    assert summary["token_retention_bps"] == 5000
    assert {
        row["wallet"] for row in store.read_csv("analysis/retention-30/wallets.csv")
    } == {
        wallet_a,
        wallet_b,
    }


def test_launch_to_exit_orders_direct_transfers_by_block() -> None:
    route = {
        "source_wallet": "0x" + "11" * 20,
        "destination_wallet": "0x" + "22" * 20,
        "timestamp": 100,
        "block": 10,
        "tx_hash": "0x" + "aa" * 32,
        "input_tokens_raw": 1,
    }
    direct = {
        "source": "0x" + "11" * 20,
        "destination": "0x" + "33" * 20,
        "timestamp": 100,
        "block": 20,
        "tx_hash": "0x" + "bb" * 32,
        "tokens_raw": 1,
    }
    assert [edge["block"] for edge in _edges([route], [direct])] == [10, 20]


def test_entry_cohort_before_launch_uses_entry_time(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": "0x" + "11" * 20,
                "first_activity_seconds": "5",
                "entry_phase": "v4",
                "open": "False",
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "22" * 20,
        supply=10**27,
        start_block=1,
        start_timestamp=1000,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_entry_cohorts(store, profile, minutes=30)
    assert summary["rows"][0]["before_launch"] is False
