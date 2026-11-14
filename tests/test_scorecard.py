from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.wallets.scorecard import analyze_wallets
from pons_analysis.storage.store import ArtifactStore


def test_scorecard_does_not_turn_unknown_net_into_zero(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": "0x" + "11" * 20,
                "tokens_end": "1.0",
                "realized_quote_eth": "0",
                "unrealized_quote_eth": "",
                "gas_quote_eth": "0",
                "net_quote_eth": "",
                "basis_deployed_eth": "1.0",
                "holding_seconds": "1",
                "trade_count": "1",
            }
        ],
    )
    store.write_json("analysis/positions-30/summary.json", {"performance": {}})
    profile = Pons.launch(
        token="0x" + "22" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_wallets(store, profile, minutes=30)
    assert summary["net_quote_eth"] is None
    assert summary["profitable_wallets"] is None
    assert summary["losing_wallets"] is None
    assert summary["flat_wallets"] is None
    assert summary["net_roi_bps"] is None
    assert store.read_csv("analysis/wallets-30/wallets.csv")[0]["net_quote_eth"] == ""
