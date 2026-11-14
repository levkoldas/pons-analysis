"""Blockscout funding evidence collection."""

from collections.abc import Iterable
from typing import Any

from pons_analysis.core.errors import IncompleteHistory, InvariantError
from pons_analysis.core.evm import addr
from pons_analysis.core.rows import row_int as _row_int
from pons_analysis.providers.blockscout import BlockscoutProvider
from pons_analysis.providers.rpc import RpcProvider
from pons_analysis.storage.store import ArtifactStore


def _page_below_start(data: dict[str, Any], start_block: int) -> bool:
    blocks = [
        _row_int(row, "block_number")
        for row in data.get("items", [])
        if isinstance(row, dict) and row.get("block_number") is not None
    ]
    return bool(blocks) and min(blocks) < start_block


def collect_funding(
    blockscout: BlockscoutProvider,
    rpc: RpcProvider,
    store: ArtifactStore,
    *,
    wallets: Iterable[str],
    start_block: int | None = None,
    cap: int = 100,
    offline: bool = False,
) -> dict[str, Any]:
    """Collect Blockscout histories and current chain state for funding wallets."""
    if offline:
        raise InvariantError(
            "Funding collection needs live nonce, balance, and code observations"
        )
    if cap < 1:
        raise ValueError("Funding page cap must be positive")
    if start_block is not None and start_block < 0:
        raise ValueError("Funding start block must be non-negative")
    addresses = tuple(sorted({addr(item) for item in wallets}))
    if not addresses:
        raise ValueError("At least one funding wallet is required")
    counts = {"transactions": 0, "internal_transfers": 0}
    stop = (
        (lambda data: _page_below_start(data, start_block))
        if start_block is not None
        else None
    )
    for wallet in addresses:
        transactions = blockscout.address_transactions(wallet, cap=cap, stop=stop)
        if not transactions.complete:
            raise IncompleteHistory(transactions.model_dump())
        internals = blockscout.address_internal_transfers(wallet, cap=cap, stop=stop)
        if not internals.complete:
            raise IncompleteHistory(internals.model_dump())
        tx_rows = [
            row
            for row in transactions.items
            if start_block is None or _row_int(row, "block_number") >= start_block
        ]
        internal_rows = [
            row
            for row in internals.items
            if start_block is None or _row_int(row, "block_number") >= start_block
        ]
        nonce = rpc.transaction_count(wallet)
        balance = rpc.balance(wallet)
        code = rpc.code(wallet)
        directory = f"evidence/funding/wallets/{wallet}"
        meta = {
            "wallet": wallet,
            "transactions": len(tx_rows),
            "internal_transfers": len(internal_rows),
            "transaction_pages": transactions.pages,
            "internal_transfer_pages": internals.pages,
            "nonce": nonce,
            "balance_raw": balance,
            "is_contract": code not in ("", "0x", "0x0"),
            "start_block": start_block,
        }
        store.write_json(f"{directory}/transactions.json", tx_rows)
        store.write_json(f"{directory}/internal_transfers.json", internal_rows)
        store.write_json(f"{directory}/meta.json", meta)
        counts["transactions"] += len(tx_rows)
        counts["internal_transfers"] += len(internal_rows)
    return {
        "wallets": len(addresses),
        "transactions": counts["transactions"],
        "internal_transfers": counts["internal_transfers"],
        "start_block": start_block,
    }
