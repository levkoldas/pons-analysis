from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.clusters.graph import _round_trips
from pons_analysis.analytics.clusters.quality import analyze_cluster_quality
from pons_analysis.storage.store import ArtifactStore


def test_round_trips_use_transaction_index_for_same_block_order(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/positions-30/trade_legs.csv",
        [
            {
                "token_wallet": wallet,
                "timestamp": 100,
                "block": 1,
                "tx_index": 0,
                "log_index": 40,
                "side": "sell",
                "tokens_raw": 100,
                "quote_net_raw": 50,
                "tx_hash": "0x" + "aa" * 32,
            },
            {
                "token_wallet": wallet,
                "timestamp": 100,
                "block": 1,
                "tx_index": 7,
                "log_index": 5,
                "side": "buy",
                "tokens_raw": 100,
                "quote_net_raw": 50,
                "tx_hash": "0x" + "bb" * 32,
            },
        ],
    )
    profile = Pons.launch(
        token="0x" + "22" * 20,
        supply=10**27,
        start_block=1,
        start_timestamp=0,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    trips, behavior, totals = _round_trips(store, 30, profile)
    assert trips == []
    assert behavior[wallet]["unmatched_sell_tokens_raw"] == 100
    assert totals["unmatched_sell_tokens_raw"] == 100


def test_cluster_roi_uses_sale_pnl_not_net_cash(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_json("analysis/clusters/summary.json", {"minutes": 30, "clusters": 1})
    store.write_csv(
        "analysis/clusters/clusters.csv",
        [{"cluster_id": "c1", "wallets": 1}],
    )
    store.write_csv(
        "analysis/clusters/wallets.csv",
        [{"wallet": wallet, "cluster_id": "c1"}],
    )
    store.write_json("analysis/execution-30/summary.json", {"minutes": 30})
    store.write_csv("analysis/execution-30/wallets.csv", [], fields=["wallet"])
    store.write_json("analysis/fees-30/summary.json", {"minutes": 30})
    store.write_csv("analysis/fees-30/wallets.csv", [], fields=["wallet"])
    store.write_json("analysis/lifecycle-30/summary.json", {"minutes": 30})
    store.write_csv(
        "analysis/lifecycle-30/wallets.csv",
        [
            {
                "wallet": wallet,
                "status": "closed",
                "basis_deployed_eth": str(50 * 10**-18),
                "sale_pnl_eth": str(30 * 10**-18),
                "unrealized_quote_eth": "0",
                "gas_quote_eth": "0",
                "net_quote_eth": str(-20 * 10**-18),
                "net_roi_bps": "6000",
                "entry_phase": "v4",
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "22" * 20,
        supply=10**27,
        start_block=1,
        start_timestamp=0,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_cluster_quality(store, profile, minutes=30)
    assert summary["rows"][0]["net_roi_bps"] == 6000
