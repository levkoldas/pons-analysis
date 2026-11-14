import pytest
from eth_abi import encode

from pons_analysis import MigrationCut, Pons
from pons_analysis.analytics.market.trajectory import _v4_events
from pons_analysis.analytics.market.window import _block_timestamp
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import RpcLog


def test_v4_negative_tick_is_sign_extended() -> None:
    token = "0x" + "11" * 20
    profile = Pons.launch(
        token=token,
        supply=10**27,
        start_block=1,
        start_timestamp=0,
        migration=MigrationCut(block=1, tx_index=0, log_index=0),
    )
    data = (
        "0x"
        + encode(
            ["int128", "int128", "uint160", "uint128", "int24", "uint24"],
            [-(10**18), 10**21, 2**96, 10**24, -92103, 3000],
        ).hex()
    )
    log = RpcLog(
        address=profile.manager or token,
        topics=[],
        data=data,
        blockNumber=1,
        transactionHash="0x" + "aa" * 32,
        transactionIndex=0,
        logIndex=0,
    )
    events, _ = _v4_events([log], {1: 0}, profile)
    assert events[0]["tick"] == -92103


def test_window_requires_block_timestamps() -> None:
    assert _block_timestamp({1: 10}, 1) == 10
    with pytest.raises(InvariantError):
        _block_timestamp({}, 1)
