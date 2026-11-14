import pytest

from pons_analysis.analytics.common.ethflow import balance_history, wallet_balance_sheet
from pons_analysis.core.accounting.amm import Q96, net_after_fees, v4_price_eth
from pons_analysis.core.accounting.cashflow import next_nonce_payment

WALLET = "0x" + "11" * 20


def test_v4_price_scales_token_decimals() -> None:
    assert v4_price_eth(Q96, 18) == pytest.approx(1.0)
    assert v4_price_eth(Q96, 9) == pytest.approx(1e-9)


def test_contract_creation_value_is_an_outflow() -> None:
    transaction = {
        "from": {"hash": WALLET},
        "to": None,
        "value": "100",
        "gas_used": "21000",
        "gas_price": "2",
        "status": "ok",
        "block_number": 1,
        "hash": "0x" + "aa" * 32,
    }
    sheet = wallet_balance_sheet([transaction], [], WALLET)
    assert sheet["ext_out"] == 100
    assert sheet["net"] == -42100
    history = balance_history([transaction], [], WALLET)
    assert history["final"] == -42100
    assert history["events"][0]["direction"] == "out"


def test_next_nonce_payment_reads_blockscout_raw_input() -> None:
    wallets = [{"from": {"hash": WALLET}, "nonce": "0x6", "raw_input": "0xDEADBEEF"}]
    sale = {"from": {"hash": WALLET}, "nonce": "0x5"}
    assert next_nonce_payment(wallets, sale, selector="0xdeadbeef") is wallets[0]


def test_combined_fees_cannot_exceed_gross() -> None:
    with pytest.raises(ValueError):
        net_after_fees(1, 10_000, 10_000)
