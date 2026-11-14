from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.comparison import compare_windows
from pons_analysis.storage.store import ArtifactStore


def test_comparison_keeps_unknown_overlap_net_null(tmp_path):
    store = ArtifactStore(tmp_path)
    wallet_a = "0x" + "1" * 40
    wallet_b = "0x" + "2" * 40
    for minutes, net in ((30, "1"), (60, "2")):
        store.write_json(
            f"analysis/positions-{minutes}/summary.json",
            {"minutes": minutes, "wallets": 2, "trades": 2, "transactions": 2},
        )
        store.write_csv(
            f"analysis/positions-{minutes}/positions.csv",
            [
                {"wallet": wallet_a, "net_quote_eth": ""},
                {"wallet": wallet_b, "net_quote_eth": net},
            ],
        )
    profile = Pons.launch(
        token="0x" + "3" * 40,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = compare_windows(
        store, profile, left_minutes=30, right_minutes=60, output="analysis/cmp.json"
    )
    overlap = summary["wallet_overlap"]
    assert overlap["overlap_wallets"] == 2
    assert overlap["overlap_net_left_eth"] is None
    assert overlap["overlap_net_right_eth"] is None
    assert overlap["overlap_net_delta_eth"] is None
