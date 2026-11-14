"""Validated provider payloads plus the protocol and launch domain models.

Raw provider and artifact payloads use Pydantic at the boundary. The immutable
``Launch`` object is deliberately a plain dataclass: it is cheap to construct,
safe to pass between threads, and independent of configuration or I/O.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated, Any

from eth_abi import encode as abi_encode
from eth_utils import is_address, is_hex, keccak
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

DEFAULT_RPC_ENDPOINTS = (
    "https://rpc.mainnet.chain.robinhood.com",
    "https://robinhood-rpc.publicnode.com",
)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _address(value: str) -> str:
    value = value.strip()
    if not value.startswith("0x") or not is_address(value):
        raise ValueError("expected a 20-byte 0x-prefixed address")
    return value.lower()


def _data(value: str) -> str:
    value = value.strip().lower()
    if not value.startswith("0x") or not is_hex(value) or len(value) % 2:
        raise ValueError("expected even-length 0x-prefixed hex data")
    return value


def _hash(value: str) -> str:
    value = value.strip().lower()
    if not value.startswith("0x") or len(value) != 66 or not is_hex(value):
        raise ValueError("expected a 32-byte 0x-prefixed hash")
    return value


Address = Annotated[str, AfterValidator(_address)]
HexData = Annotated[str, AfterValidator(_data)]
Hash32 = Annotated[str, AfterValidator(_hash)]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_by_name=True)


class RpcLog(StrictModel):
    address: Address
    topics: list[HexData]
    data: HexData
    block_number: int = Field(alias="blockNumber")
    transaction_hash: Hash32 = Field(alias="transactionHash")
    transaction_index: int = Field(alias="transactionIndex")
    log_index: int = Field(alias="logIndex")
    block_hash: Hash32 | None = Field(default=None, alias="blockHash")
    removed: bool = False

    @field_validator("block_number", "transaction_index", "log_index", mode="before")
    @classmethod
    def _hex_int(cls, value):
        return int(value, 16) if isinstance(value, str) else value

    def position(self) -> tuple[int, int, int]:
        return (self.block_number, self.transaction_index, self.log_index)


class RpcReceipt(StrictModel):
    transaction_hash: Hash32 = Field(alias="transactionHash")
    status: int
    block_number: int = Field(alias="blockNumber")
    transaction_index: int = Field(alias="transactionIndex")
    from_address: Address = Field(alias="from")
    to: Address | None = None
    gas_used: int = Field(alias="gasUsed")
    effective_gas_price: int | None = Field(default=None, alias="effectiveGasPrice")
    logs: list[RpcLog] = Field(default_factory=list)
    block_timestamp: int | None = None

    @field_validator(
        "status",
        "block_number",
        "transaction_index",
        "gas_used",
        "effective_gas_price",
        mode="before",
    )
    @classmethod
    def _hex_int(cls, value):
        return int(value, 16) if isinstance(value, str) else value

    @property
    def succeeded(self) -> bool:
        return self.status == 1

    @property
    def gas_cost(self) -> int:
        return self.gas_used * (self.effective_gas_price or 0)


class RpcTransaction(StrictModel):
    hash: Hash32
    block_number: int | None = Field(default=None, alias="blockNumber")
    block_hash: Hash32 | None = Field(default=None, alias="blockHash")
    transaction_index: int | None = Field(default=None, alias="transactionIndex")
    from_address: Address = Field(alias="from")
    to: Address | None = None
    value: int
    nonce: int
    input: HexData
    gas: int
    gas_price: int | None = Field(default=None, alias="gasPrice")
    max_fee_per_gas: int | None = Field(default=None, alias="maxFeePerGas")
    max_priority_fee_per_gas: int | None = Field(
        default=None, alias="maxPriorityFeePerGas"
    )
    created_contract: Address | None = Field(default=None, alias="creates")

    @field_validator(
        "block_number",
        "transaction_index",
        "value",
        "nonce",
        "gas",
        "gas_price",
        "max_fee_per_gas",
        "max_priority_fee_per_gas",
        mode="before",
    )
    @classmethod
    def _hex_int(cls, value):
        return int(value, 16) if isinstance(value, str) else value


class RpcBlock(StrictModel):
    number: int
    hash: Hash32
    parent_hash: Hash32 = Field(alias="parentHash")
    timestamp: int
    transactions: list[str | dict[str, Any]] = Field(default_factory=list)

    @field_validator("number", "timestamp", mode="before")
    @classmethod
    def _hex_int(cls, value):
        return int(value, 16) if isinstance(value, str) else value


class PageResult(StrictModel):
    items: list[Any]
    complete: bool
    pages: int


class RpcRequest(StrictModel):
    method: NonEmpty
    params: list[Any] = Field(default_factory=list)


class CacheRecord(StrictModel):
    request: dict[str, Any]
    response: Any
    retrieved_at: float = Field(default_factory=time.time)
    source: NonEmpty
    chain_id: int | None = None
    sha256: Hash32 | None = None


class Coverage(StrictModel):
    start_block: int
    end_block: int
    start_timestamp: int
    end_timestamp_exclusive: int
    head: int
    transactions: int
    next_block_timestamp: int | None = None
    end_block_timestamp: int | None = None
    created_at: float = Field(default_factory=time.time)


class LaunchRecord(StrictModel):
    token: Address
    curve: Address
    deployer: Address
    creator_fee_recipient: Address | None = None
    pair_token: Address | None = None
    graduation_threshold: int | None = None
    pool_fee: int | None = None
    tick_spacing: int | None = None
    creator_tax_bps: int | None = None
    buyback_enabled: bool | None = None
    phase: int | None = None
    swept_quote: int | None = None
    swept_tokens: int | None = None
    swept_at: int | None = None
    exists: bool = True


class MigrationCut(StrictModel):
    model_config = ConfigDict(extra="ignore", validate_by_name=True, frozen=True)

    block: int = Field(ge=0)
    tx_index: int = Field(ge=0)
    log_index: int = Field(ge=0)

    def position(self) -> tuple[int, int, int]:
        return (self.block, self.tx_index, self.log_index)


@dataclass(frozen=True, slots=True)
class PonsProtocol:
    """Static PONS protocol facts shared by every token launch."""

    name: str = "pons"
    chain: str = "robinhood"
    chain_id: int = 4663
    manager: str = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
    router: str = "0xb06983db4fad9cd94efbf9088c364ebcacde1214"
    hook: str = "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"
    curve: str | None = "0x2c2438f78c88439f40b636eaed748d3070049037"
    factory: str | None = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
    swap_topic: str | None = (
        "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
    )
    transfer_topic: str = TRANSFER_TOPIC
    base_fee_bps: int = 100
    creator_tax_bps: int = 300
    creator_share_bps: int = 7_000
    protocol_sweepers: tuple[str, ...] = ("0x49bbf2b70955fb3a106e084d4bfda92d334573d2",)
    windows: tuple[int, ...] = (30, 90)
    rpc_endpoints: tuple[str, ...] = DEFAULT_RPC_ENDPOINTS

    def launch(
        self,
        *,
        token: str,
        supply: int,
        start_block: int,
        start_timestamp: int,
        migration: MigrationCut | None = None,
        decimals: int = 18,
        launch_start_block: int | None = None,
        pool_id: str | None = None,
        creator_tax_bps: int | None = None,
        curve: str | None = None,
        windows: tuple[int, ...] | None = None,
    ) -> Launch:
        """Build an explicit launch without configuration files or discovery.

        ``start_block`` and ``start_timestamp`` are the analysis anchor: the
        migration block for a graduated launch, or the deployment block for a
        launch that is still trading on the bonding curve.
        """

        return Launch(
            protocol=self,
            token=_address(token),
            supply=supply,
            decimals=decimals,
            start_block=start_block,
            start_timestamp=start_timestamp,
            launch_start_block=launch_start_block,
            migration=migration,
            pool_id=pool_id,
            creator_tax_bps_override=creator_tax_bps,
            curve_override=curve,
            windows=windows or self.windows,
        )

    def pool_id_for(
        self,
        token: str,
        *,
        pair_token: str | None = None,
        pool_fee: int = 0,
        tick_spacing: int = 200,
    ) -> str:
        """Uniswap-v4 PoolId from the PoolKey; validated against PONS evidence."""

        token = _address(token)
        pair = _address(pair_token) if pair_token else "0x" + "0" * 40
        currency0, currency1 = sorted((token, pair))
        encoded = abi_encode(
            ["address", "address", "uint24", "int24", "address"],
            [currency0, currency1, pool_fee, tick_spacing, self.hook],
        )
        return "0x" + keccak(encoded).hex()


@dataclass(frozen=True, slots=True)
class Launch:
    """One token launch bound to its immutable protocol definition.

    ``migration`` is ``None`` while the token still trades on the bonding
    curve. In that case ``start_block`` and ``start_timestamp`` anchor the
    analysis at the deployment block. Once the launch graduates, the anchor
    moves to the migration cut and curve evidence before it stays in the
    launch artifacts.
    """

    protocol: PonsProtocol
    token: str
    supply: int
    decimals: int
    start_block: int
    start_timestamp: int
    migration: MigrationCut | None = None
    launch_start_block: int | None = None
    pool_id: str | None = None
    creator_tax_bps_override: int | None = None
    curve_override: str | None = None
    windows: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", _address(self.token))
        if self.supply <= 0:
            raise ValueError("supply must be positive")
        if not 0 <= self.decimals <= 36:
            raise ValueError("decimals must be between 0 and 36")
        if self.start_block < 0 or self.start_timestamp < 0:
            raise ValueError("launch block and timestamp must be non-negative")
        if self.migration is not None and self.start_block != self.migration.block:
            raise ValueError("start_block must equal the migration block")
        if self.launch_start_block is not None:
            if self.launch_start_block < 0:
                raise ValueError("launch_start_block must be non-negative")
            if self.launch_start_block > self.start_block:
                raise ValueError(
                    "launch_start_block must not follow the analysis anchor"
                )
        if self.pool_id is not None:
            object.__setattr__(self, "pool_id", self.pool_id.lower())
            if (
                not self.pool_id.startswith("0x")
                or len(self.pool_id) != 66
                or not is_hex(self.pool_id)
            ):
                raise ValueError("pool_id must be a 32-byte 0x-prefixed hash")
        if self.curve_override is not None:
            object.__setattr__(self, "curve_override", _address(self.curve_override))
        if self.creator_tax_bps_override is not None and not (
            0 <= self.creator_tax_bps_override <= 10_000
        ):
            raise ValueError("creator_tax_bps must be between 0 and 10000")
        windows = self.windows or self.protocol.windows
        if not windows or any(window <= 0 for window in windows):
            raise ValueError("analysis windows must be positive minutes")
        object.__setattr__(self, "windows", tuple(windows))

    @property
    def name(self) -> str:
        return self.protocol.name

    @property
    def migrated(self) -> bool:
        """Whether the launch has graduated from the bonding curve."""

        return self.migration is not None

    @property
    def chain(self) -> str:
        return self.protocol.chain

    @property
    def chain_id(self) -> int:
        return self.protocol.chain_id

    @property
    def manager(self) -> str:
        return self.protocol.manager

    @property
    def router(self) -> str:
        return self.protocol.router

    @property
    def hook(self) -> str:
        return self.protocol.hook

    @property
    def curve(self) -> str | None:
        return self.curve_override or self.protocol.curve

    @property
    def factory(self) -> str | None:
        return self.protocol.factory

    @property
    def swap_topic(self) -> str | None:
        return self.protocol.swap_topic

    @property
    def transfer_topic(self) -> str:
        return self.protocol.transfer_topic

    @property
    def base_fee_bps(self) -> int:
        return self.protocol.base_fee_bps

    @property
    def creator_tax_bps(self) -> int:
        if self.creator_tax_bps_override is not None:
            return self.creator_tax_bps_override
        return self.protocol.creator_tax_bps

    @property
    def creator_share_bps(self) -> int:
        return self.protocol.creator_share_bps

    @property
    def protocol_sweepers(self) -> tuple[str, ...]:
        return self.protocol.protocol_sweepers

    @property
    def rpc_endpoints(self) -> tuple[str, ...]:
        return self.protocol.rpc_endpoints
