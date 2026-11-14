from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.routes.performance import analyze_route_performance
from pons_analysis.storage.store import ArtifactStore


def test_route_performance_preserves_unknown_net(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/launch/trades.csv",
        [
            {
                "wallet": wallet,
                "tx_to": "0x" + "22" * 20,
                "selector": "0x12345678",
                "side": "buy",
                "quote_eth": "1.0",
            }
        ],
    )
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "net_quote_raw": "",
                "net_roi_bps": "",
                "basis_deployed_raw": "100",
                "realized_quote_raw": "0",
                "unrealized_quote_raw": "",
                "gas_quote_raw": "0",
                "tokens_end": "1.0",
                "open": "True",
                "entry_phase": "v4",
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "33" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_route_performance(store, profile, minutes=30)
    assert summary["net_quote_eth"] is None
    assert summary["net_roi_bps"] is None
    row = summary["top_by_net"][0]
    assert row["net_quote_eth"] is None
    assert row["net_roi_bps"] is None
    assert row["profitable_wallets"] is None


def test_route_performance_assigns_zero_to_routes_without_wallets(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    other = "0x" + "44" * 20
    store.write_csv(
        "analysis/launch/trades.csv",
        [
            {
                "wallet": wallet,
                "tx_to": "0x" + "22" * 20,
                "selector": "0x12345678",
                "side": "buy",
                "quote_eth": "1.0",
            },
            {
                "wallet": other,
                "tx_to": "0x" + "55" * 20,
                "selector": "0x87654321",
                "side": "buy",
                "quote_eth": "2.0",
            },
        ],
    )
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "net_quote_raw": str(10 * 10**18),
                "net_roi_bps": "1000",
                "basis_deployed_raw": str(10**18),
                "sale_pnl_raw": str(10**18),
                "realized_quote_raw": str(10 * 10**18),
                "unrealized_quote_raw": "0",
                "gas_quote_raw": "0",
                "tokens_end": "0",
                "open": "False",
                "entry_phase": "curve",
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "33" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
    )
    summary = analyze_route_performance(store, profile, minutes=30)
    empty = next(
        row for row in summary["top_by_net"] if row["route"] == "0x" + "55" * 20
    )
    assert empty["wallets"] == 0
    assert empty["net_quote_eth"] == 0.0
    assert empty["unrealized_quote_eth"] == 0.0
    assert summary["net_quote_eth"] == sum(
        float(row["net_quote_eth"]) for row in summary["top_by_net"]
    )
    store = ArtifactStore(tmp_path)
    wallet = "0x" + "11" * 20
    store.write_csv(
        "analysis/launch/trades.csv",
        [
            {
                "wallet": wallet,
                "tx_to": "0x" + "22" * 20,
                "selector": "0x12345678",
                "side": "buy",
                "quote_eth": "1.0",
            }
        ],
    )
    store.write_csv(
        "analysis/positions-30/positions.csv",
        [
            {
                "wallet": wallet,
                "net_quote_raw": str(-20 * 10**18),
                "net_roi_bps": "6000",
                "basis_deployed_raw": str(50 * 10**18),
                "sale_pnl_raw": str(30 * 10**18),
                "realized_quote_raw": str(-20 * 10**18),
                "unrealized_quote_raw": "0",
                "gas_quote_raw": "0",
                "tokens_end": "0",
                "open": "False",
                "entry_phase": "v4",
            }
        ],
    )
    profile = Pons.launch(
        token="0x" + "33" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    summary = analyze_route_performance(store, profile, minutes=30)
    assert summary["top_by_net"][0]["net_roi_bps"] == 6000
    assert summary["net_roi_bps"] == 6000
