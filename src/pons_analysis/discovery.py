"""PONS launch discovery and explicit launch construction."""

from eth_abi.exceptions import DecodingError

from pons_analysis.core.errors import InvariantError, ProviderError, ResolutionError
from pons_analysis.core.evm import address_word, decode_abi
from pons_analysis.core.models import (
    Launch,
    LaunchRecord,
    MigrationCut,
    PonsProtocol,
)
from pons_analysis.ports import Rpc

FACTORY_RECORD_TYPES = [
    "address",
    "address",
    "address",
    "address",
    "address",
    "uint256",
    "uint256",
    "uint256",
    "uint256",
    "bool",
    "uint256",
    "uint256",
    "uint256",
    "uint256",
    "bool",
]


def read_launch_record(
    rpc: Rpc, protocol: PonsProtocol, token: str, *, block: int | str = "latest"
) -> LaunchRecord:
    """Read and ABI-decode ``getLaunchedToken(address)``."""

    if protocol.factory is None:
        raise ResolutionError("PONS protocol has no factory address")
    result = rpc.call_contract(
        protocol.factory,
        "getLaunchedToken(address)",
        address_word(token),
        block,
    )
    try:
        values = decode_abi(FACTORY_RECORD_TYPES, result)
    except (ValueError, TypeError, DecodingError) as exc:
        raise ResolutionError("Factory record ABI could not be decoded") from exc
    if len(values) < len(FACTORY_RECORD_TYPES):
        raise ResolutionError("Factory record is shorter than the PONS layout")
    return LaunchRecord(
        token=values[0],
        curve=values[1],
        deployer=values[2],
        creator_fee_recipient=values[3],
        pair_token=values[4],
        graduation_threshold=values[5],
        pool_fee=values[6],
        tick_spacing=values[7],
        creator_tax_bps=values[8],
        buyback_enabled=values[9],
        phase=values[10],
        swept_quote=values[11],
        swept_tokens=values[12],
        swept_at=values[13],
        exists=values[14],
    )


def token_decimals(rpc: Rpc, token: str) -> int:
    data = rpc.call_contract(token, "decimals()")
    try:
        values = decode_abi(["uint8"], data)
    except (ValueError, TypeError, DecodingError) as exc:
        raise ResolutionError("Token decimals could not be decoded") from exc
    return int(values[0])


def token_supply(rpc: Rpc, token: str) -> int:
    data = rpc.call_contract(token, "totalSupply()")
    try:
        values = decode_abi(["uint256"], data)
    except (ValueError, TypeError, DecodingError) as exc:
        raise ResolutionError("Token supply could not be decoded") from exc
    return int(values[0])


def resolve_pons_launch(
    protocol: PonsProtocol,
    token: str,
    rpc: Rpc,
    *,
    migration: MigrationCut | None = None,
    launch_start_block: int | None = None,
    pool_id: str | None = None,
    supply: int | None = None,
    decimals: int | None = None,
    creator_tax_bps: int | None = None,
    head: int | None = None,
) -> Launch:
    """Resolve token metadata, pool identity, deployment, and migration.

    A graduated launch returns a migration cut. A launch that is still trading
    on the bonding curve returns ``migration=None`` with the deployment block as
    the analysis anchor.

    ``rpc`` is explicit: discovery is a network operation, not import-time
    configuration. A caller can always use :meth:`PonsProtocol.launch` with
    known values when historical state is unavailable.
    """

    record = read_launch_record(rpc, protocol, token)
    if not record.exists:
        raise ResolutionError("Factory reports no PONS launch for this token")
    decimals = decimals if decimals is not None else token_decimals(rpc, record.token)
    supply = supply if supply is not None else token_supply(rpc, record.token)
    if not 0 <= decimals <= 36:
        raise ResolutionError("Token metadata has invalid decimals")
    if supply <= 0:
        raise ResolutionError("Token metadata has zero or negative supply")
    if launch_start_block is not None:
        launch_start = launch_start_block
    else:
        try:
            launch_start = rpc.creation_block(record.token)
        except ProviderError as exc:
            raise ResolutionError(
                "Cannot discover the token deployment block; pass launch_start_block"
            ) from exc
    if pool_id is not None:
        resolved_pool = pool_id
    else:
        pool_fee = record.pool_fee or 0
        tick_spacing = record.tick_spacing if record.tick_spacing is not None else 200
        if not 0 <= pool_fee <= 0xFFFFFF:
            raise ResolutionError("Factory pool fee is outside uint24")
        if not -(2**23) <= tick_spacing < 2**23:
            raise ResolutionError("Factory tick spacing is outside int24")
        resolved_pool = protocol.pool_id_for(
            record.token,
            pair_token=record.pair_token,
            pool_fee=pool_fee,
            tick_spacing=tick_spacing,
        )
    if migration is None and (record.phase is None or record.phase >= 2):
        if protocol.swap_topic is None:
            raise ResolutionError("Protocol has no v4 swap topic")
        upper = rpc.latest_block() if head is None else head
        first = rpc.first_log(
            protocol.manager,
            launch_start,
            upper,
            [protocol.swap_topic, resolved_pool],
        )
        if first is None:
            raise ResolutionError(
                "No v4 migration swap found; pass an explicit migration cut"
            )
        migration = MigrationCut(
            block=first.block_number,
            tx_index=first.transaction_index,
            log_index=first.log_index,
        )
    start_block = migration.block if migration is not None else launch_start
    start_timestamp = rpc.block(start_block).timestamp
    if start_timestamp < 0:
        raise InvariantError("Negative launch timestamp from RPC")
    return protocol.launch(
        token=record.token,
        supply=supply,
        decimals=decimals,
        start_block=start_block,
        start_timestamp=start_timestamp,
        launch_start_block=launch_start,
        migration=migration,
        pool_id=resolved_pool,
        creator_tax_bps=creator_tax_bps
        if creator_tax_bps is not None
        else record.creator_tax_bps,
        curve=record.curve,
    )
