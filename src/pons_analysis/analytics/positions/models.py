"""Position domain types and FIFO ledger state."""

import collections
from dataclasses import dataclass, field


@dataclass
class Lot:
    tokens: int
    cost: int
    timestamp: int
    sequence: int = 0


@dataclass
class TradeLeg:
    block: int
    tx_index: int
    log_index: int
    tx_hash: str
    timestamp: int
    phase: str
    side: str
    token_wallet: str
    quote_wallet: str
    funding_wallet: str
    tokens: int
    quote_gross: int
    quote_net: int
    fee_quote: int
    tax_quote: int
    fee_token: int
    tax_token: int
    resolved_intermediary: str | None
    cross_wallet: bool
    sequence: int = 0

    def position(self) -> tuple[int, int, int]:
        return (self.block, self.tx_index, self.log_index)


@dataclass
class _Ledger:
    lots: dict[str, collections.deque[Lot]] = field(
        default_factory=lambda: collections.defaultdict(collections.deque)
    )
    # Running token total avoids rescanning every lot on each disposal.
    available: collections.Counter[str] = field(default_factory=collections.Counter)
    next_sequence: int = 0
    stats: dict[str, collections.Counter] = field(
        default_factory=lambda: collections.defaultdict(collections.Counter)
    )
