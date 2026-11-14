import pytest
from eth_abi import encode

from pons_analysis import (
    Launch,
    MigrationCut,
    Pons,
    ResolutionError,
)
from pons_analysis.core.models import LaunchRecord, RpcBlock, RpcLog
from pons_analysis.discovery import (
    FACTORY_RECORD_TYPES,
    read_launch_record,
    resolve_pons_launch,
)

TOKEN = "0x2416A8bC9c617628A9105F6315F0C32E0A438860"
ZERO = "0x" + "0" * 40
POOL = "0x077fcab0018a28dd0cc50ac1e62f224a0206252636cd4c419d6649a8c7806ea2"


def test_pool_id_matches_known_pons_pool() -> None:
    assert Pons.protocol.pool_id_for(TOKEN, pair_token=ZERO) == POOL


def test_launch_normalizes_token_and_preserves_integer_supply() -> None:
    launch = Pons.launch(
        token=TOKEN,
        supply=10**27,
        start_block=56007631,
        start_timestamp=1788700729,
        migration=MigrationCut(block=56007631, tx_index=14, log_index=76),
        pool_id=POOL,
    )
    assert isinstance(launch, Launch)
    assert launch.token == TOKEN.lower()
    assert launch.supply == 10**27
    assert launch.name == "pons"


def test_address_requires_0x_prefix() -> None:
    with pytest.raises(ValueError):
        Pons.launch(
            token="ab" * 20,
            supply=1,
            start_block=0,
            start_timestamp=0,
            migration=MigrationCut(block=0, tx_index=0, log_index=0),
        )


def test_unprefixed_pool_hash_rejected() -> None:
    with pytest.raises(ValueError):
        Pons.launch(
            token=TOKEN,
            supply=1,
            start_block=0,
            start_timestamp=0,
            migration=MigrationCut(block=0, tx_index=0, log_index=0),
            pool_id="cd" * 33,
        )


def test_invalid_pool_id_rejected() -> None:
    with pytest.raises(ValueError):
        Pons.launch(
            token=TOKEN,
            supply=1,
            start_block=0,
            start_timestamp=0,
            migration=MigrationCut(block=0, tx_index=0, log_index=0),
            pool_id="0x1234",
        )


def test_launch_start_block_must_match_migration() -> None:
    with pytest.raises(ValueError, match="start_block"):
        Pons.launch(
            token=TOKEN,
            supply=1,
            start_block=10,
            start_timestamp=0,
            migration=MigrationCut(block=11, tx_index=0, log_index=0),
        )


def test_curve_launch_start_block_must_not_follow_anchor() -> None:
    with pytest.raises(ValueError, match="launch_start_block"):
        Pons.launch(
            token=TOKEN,
            supply=1,
            start_block=10,
            start_timestamp=0,
            launch_start_block=11,
        )


def test_protocol_launch_requires_positive_supply() -> None:
    with pytest.raises(ValueError):
        Pons.launch(
            token=TOKEN,
            supply=0,
            start_block=0,
            start_timestamp=0,
            migration=MigrationCut(block=0, tx_index=0, log_index=0),
        )


class FakeRpc:
    chain_id = 4663

    def __init__(self, factory_data: str):
        self.factory_data = factory_data
        self.logs_calls: list[tuple[int, int]] = []

    def call_contract(
        self,
        address: str,
        signature: str | None = None,
        args: str = "",
        block: int | str = "latest",
        *,
        data: str | None = None,
    ) -> str:
        if signature == "getLaunchedToken(address)":
            return self.factory_data
        if signature == "decimals()":
            return "0x" + encode(["uint8"], [18]).hex()
        if signature == "totalSupply()":
            return "0x" + encode(["uint256"], [10**27]).hex()
        raise AssertionError(signature)

    def creation_block(self, address: str, lo: int = 0, hi: int | None = None) -> int:
        return 100

    def latest_block(self) -> int:
        return 1000

    def logs(self, *args, **kwargs):
        return [
            RpcLog(
                address=args[0],
                topics=[Pons.protocol.swap_topic or "", POOL],
                data="0x",
                blockNumber=500,
                transactionHash="0x" + "1" * 64,
                transactionIndex=2,
                logIndex=3,
            )
        ]

    def first_log(self, *args, **kwargs):
        logs = self.logs(*args, **kwargs)
        return logs[0] if logs else None

    def block(self, number: int, *, full: bool = False) -> RpcBlock:
        return RpcBlock(
            number=number,
            hash="0x" + "2" * 64,
            parentHash="0x" + "3" * 64,
            timestamp=1788700729,
        )


def _factory_data(*, pool_fee: int = 0, tick_spacing: int = 200, phase: int = 2) -> str:
    values = [
        TOKEN.lower(),
        "0x2c2438f78c88439f40b636eaed748d3070049037",
        "0x64c95b9487f36c4ab1852f00c9c81e5a8a38b2be",
        "0x64c95b9487f36c4ab1852f00c9c81e5a8a38b2be",
        ZERO,
        4_200_000_000_000_000_000,
        pool_fee,
        tick_spacing,
        200,
        False,
        phase,
        0,
        0,
        0,
        True,
    ]
    return "0x" + encode(FACTORY_RECORD_TYPES, values).hex()


def test_raw_log_hex_requires_0x_prefix() -> None:
    with pytest.raises(ValueError):
        RpcLog(
            address=TOKEN.lower(),
            topics=["0x" + "aa" * 32],
            data="abcd",
            blockNumber=1,
            transactionHash="0x" + "bb" * 32,
            transactionIndex=0,
            logIndex=0,
        )
    with pytest.raises(ValueError):
        RpcLog(
            address=TOKEN.lower(),
            topics=["0x" + "aa" * 32],
            data="0x",
            blockNumber=1,
            transactionHash="ab" * 32,
            transactionIndex=0,
            logIndex=0,
        )


def test_model_accepts_alias_and_field_name() -> None:
    common = {
        "address": TOKEN.lower(),
        "topics": ["0x" + "aa" * 32],
        "data": "0x",
    }
    aliased = RpcLog(
        **common,
        blockNumber=7,
        transactionHash="0x" + "bb" * 32,
        transactionIndex=0,
        logIndex=0,
    )
    named = RpcLog(
        **common,
        block_number=7,
        transaction_hash="0x" + "bb" * 32,
        transaction_index=0,
        log_index=0,
    )
    assert aliased.model_dump() == named.model_dump()
    assert named.block_number == 7


def test_factory_decode_error_is_resolution_error() -> None:
    with pytest.raises(ResolutionError):
        read_launch_record(FakeRpc("0x0000"), Pons.protocol, TOKEN)


def test_factory_record_decodes_with_eth_abi() -> None:
    record = read_launch_record(FakeRpc(_factory_data()), Pons.protocol, TOKEN)
    assert isinstance(record, LaunchRecord)
    assert record.token == TOKEN.lower()
    assert record.tick_spacing == 200
    assert record.exists is True


def test_resolve_wraps_malformed_token_metadata() -> None:
    class BadMetadata(FakeRpc):
        def call_contract(
            self, address, signature=None, args="", block="latest", *, data=None
        ):
            if signature == "decimals()":
                return "0x0000"
            return super().call_contract(address, signature, args, block, data=data)

    with pytest.raises(ResolutionError):
        resolve_pons_launch(
            Pons.protocol,
            TOKEN,
            BadMetadata(_factory_data()),
            launch_start_block=100,
        )


def test_resolve_builds_explicit_launch_from_chain_metadata() -> None:
    launch = resolve_pons_launch(
        Pons.protocol,
        TOKEN,
        FakeRpc(_factory_data()),
        launch_start_block=100,
    )
    assert launch.start_block == 500
    assert launch.launch_start_block == 100
    assert launch.start_timestamp == 1788700729
    assert launch.pool_id == POOL
    assert launch.curve == "0x2c2438f78c88439f40b636eaed748d3070049037"
    assert launch.supply == 10**27
    assert launch.creator_tax_bps == 200


def test_resolve_builds_curve_launch_without_a_migration() -> None:
    launch = resolve_pons_launch(
        Pons.protocol,
        TOKEN,
        FakeRpc(_factory_data(phase=0)),
        launch_start_block=100,
    )
    assert launch.migrated is False
    assert launch.migration is None
    assert launch.start_block == 100
    assert launch.start_timestamp == 1788700729
    assert launch.launch_start_block == 100
    assert launch.pool_id == POOL


def test_collect_launch_rejects_zero_head(tmp_path) -> None:
    launch = Pons.launch(
        token=TOKEN,
        supply=1,
        start_block=10,
        start_timestamp=0,
        launch_start_block=0,
        migration=MigrationCut(block=10, tx_index=0, log_index=0),
    )
    from pons_analysis import LaunchRun
    from pons_analysis.core.errors import InvariantError

    run = LaunchRun(launch, tmp_path)
    with pytest.raises(InvariantError):
        run.collect_launch(head=0)
    run.close()


def test_resolve_requires_start_block_when_archive_state_is_unavailable() -> None:
    class NoArchive(FakeRpc):
        def creation_block(
            self, address: str, lo: int = 0, hi: int | None = None
        ) -> int:
            from pons_analysis.core.errors import ProviderError

            raise ProviderError("historical state unavailable")

    with pytest.raises(ResolutionError):
        resolve_pons_launch(Pons.protocol, TOKEN, NoArchive(_factory_data()))


def test_out_of_range_pool_key_is_a_resolution_error() -> None:
    with pytest.raises(ResolutionError):
        resolve_pons_launch(
            Pons.protocol,
            TOKEN,
            FakeRpc(_factory_data(pool_fee=2**24)),
            launch_start_block=100,
        )
