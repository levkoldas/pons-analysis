from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.funding.provenance import analyze_provenance
from pons_analysis.storage.store import ArtifactStore


def test_protocol_outflow_is_not_treated_as_external_funding(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "aa" * 20
    store.write_csv(
        "analysis/funding/edges.csv",
        [
            {
                "source": Pons.protocol.router,
                "destination": wallet,
                "timestamp": 2,
                "block": 1,
                "value_eth": 1.0,
            }
        ],
    )
    store.write_csv(
        "analysis/funding/wallets.csv",
        [{"wallet": wallet, "fresh": "false"}],
    )
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "first_trade_seconds": 10,
                "entry_phase": "v4",
                "tokens_end": 1.0,
                "net_quote_eth": 0.0,
                "trade_count": 1,
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "bb" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    analyze_provenance(store, profile, minutes=30)
    rows = store.read_csv("analysis/provenance-30/wallets.csv")
    assert rows[0]["first_inflow_source"] == ""
    assert rows[0]["prefunded"] == ""
