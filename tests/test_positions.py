import pytest
from eth_abi import encode

from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.positions.engine import _hook_fees
from pons_analysis.analytics.positions.ledger import (
    _add_lot,
    _move_lots,
    _take_lots,
)
from pons_analysis.analytics.positions.mark import _mark_value
from pons_analysis.analytics.positions.matching import _resolve_endpoint
from pons_analysis.analytics.positions.models import _Ledger
from pons_analysis.analytics.positions.summary import _pnl_histogram
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import sig
from pons_analysis.core.models import RpcLog, RpcReceipt


def test_moved_lots_merge_into_destination_fifo_order() -> None:
    ledger = _Ledger()
    _add_lot(ledger, "a", 100, 100, 1)
    _add_lot(ledger, "b", 100, 1000, 2)
    _move_lots(ledger, "a", "b", 100, context="test")
    assert [(lot.tokens, lot.cost, lot.timestamp) for lot in ledger.lots["b"]] == [
        (100, 100, 1),
        (100, 1000, 2),
    ]
    assert _take_lots(ledger, "b", 100, context="test") == 100


def test_hook_fees_are_attributed_to_each_swap() -> None:
    zero = "0x" + "0" * 40
    pool = "0x" + "11" * 32
    profile = Pons.protocol.launch(
        token="0x" + "33" * 20,
        supply=1,
        start_block=1,
        start_timestamp=1,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
        pool_id=pool,
    )
    hook = profile.hook
    swap_topic = profile.swap_topic
    fee_topic = sig("HookFeeCollected(bytes32,address,uint256,uint256)")

    def fee_log(index: int, amount: int) -> RpcLog:
        data = "0x" + encode(["address", "uint256", "uint256"], [zero, amount, 0]).hex()
        return RpcLog(
            address=hook,
            topics=[fee_topic, pool],
            data=data,
            blockNumber=1,
            transactionHash="0x" + "44" * 32,
            transactionIndex=0,
            logIndex=index,
        )

    def swap_log(index: int) -> RpcLog:
        return RpcLog(
            address="0x" + "55" * 20,
            topics=[swap_topic, pool],
            data="0x" + "00" * 32 * 6,
            blockNumber=1,
            transactionHash="0x" + "44" * 32,
            transactionIndex=0,
            logIndex=index,
        )

    swaps = [swap_log(1), swap_log(4)]
    receipt = RpcReceipt(
        transactionHash="0x" + "44" * 32,
        status=1,
        blockNumber=1,
        transactionIndex=0,
        **{"from": zero},
        gasUsed=1,
        logs=[swaps[0], fee_log(2, 10), swaps[1], fee_log(5, 20)],
    )
    assert _hook_fees(receipt, profile, swaps[0]) == (10, 0, 0, 0)
    assert _hook_fees(receipt, profile, swaps[1]) == (20, 0, 0, 0)


def test_split_router_path_is_ambiguous() -> None:
    router = "0x" + "22" * 20
    trade = RpcLog(
        address="0x" + "55" * 20,
        topics=["0x" + "aa" * 32, "0x" + "00" * 32, router],
        data="0x" + "00" * 32 * 6,
        blockNumber=1,
        transactionHash="0x" + "44" * 32,
        transactionIndex=0,
        logIndex=1,
    )
    transfer = RpcLog(
        address="0x" + "33" * 20,
        topics=["0x" + "dd" * 32, router, "0x" + "11" * 20],
        data="0x" + "3c" * 32,
        blockNumber=1,
        transactionHash="0x" + "44" * 32,
        transactionIndex=0,
        logIndex=2,
    )
    other = "0x" + "12" * 20
    outgoing = {
        ("0x" + "44" * 32, router, 60): [("0x" + "11" * 20, transfer)],
        ("0x" + "44" * 32, router, 40): [(other, transfer)],
    }
    with pytest.raises(InvariantError, match="Ambiguous split"):
        _resolve_endpoint(
            outgoing,
            {},
            trade,
            side="buy",
            protocol={router},
            amount=100,
        )


def test_zero_tokens_have_zero_mark_value_without_a_mark() -> None:
    assert _mark_value(0, None) == 0


def test_pnl_histogram_includes_the_maximum() -> None:
    histogram = _pnl_histogram([0, 1])
    assert sum(bucket["count"] for bucket in histogram) == 2
    assert histogram[-1]["upper_net_raw"] == 1
    assert histogram[-1]["count"] == 1


def test_moved_lot_precedes_same_block_destination_lot() -> None:
    ledger = _Ledger()
    _add_lot(ledger, "s", 100, 100, 1)
    _add_lot(ledger, "d", 100, 1000, 1)
    _move_lots(ledger, "s", "d", 100, context="test")
    assert _take_lots(ledger, "d", 100, context="test") == 100
