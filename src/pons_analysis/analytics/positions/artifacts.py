"""Position artifact schemas, readers, and writers."""

from collections.abc import Iterable
from typing import Any

from pons_analysis.analytics.common.artifacts import read_list, utc
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch, RpcReceipt
from pons_analysis.storage.store import ArtifactStore

from .mark import _mark_value
from .models import TradeLeg, _Ledger

POSITION_FIELDS = (
    "wallet",
    "cohort",
    "tokens_end_raw",
    "tokens_end",
    "tokens_in_raw",
    "tokens_in",
    "tokens_out_raw",
    "tokens_out",
    "transfer_in_raw",
    "transfer_in",
    "transfer_out_raw",
    "transfer_out",
    "external_in_raw",
    "external_in",
    "external_out_raw",
    "external_out",
    "bought_tokens_raw",
    "bought_tokens",
    "sold_tokens_raw",
    "sold_tokens",
    "quote_spent_raw",
    "quote_spent_eth",
    "quote_received_gross_raw",
    "quote_received_gross_eth",
    "quote_received_net_raw",
    "quote_received_net_eth",
    "fee_quote_raw",
    "tax_quote_raw",
    "token_fee_raw",
    "token_tax_raw",
    "realized_quote_raw",
    "realized_quote_eth",
    "unrealized_quote_raw",
    "unrealized_quote_eth",
    "gas_quote_raw",
    "gas_quote_eth",
    "net_quote_raw",
    "net_quote_eth",
    "cost_basis_remaining_raw",
    "sold_basis_raw",
    "basis_deployed_raw",
    "sale_pnl_raw",
    "external_out_basis_raw",
    "transfer_out_basis_raw",
    "realized_roi_bps",
    "net_roi_bps",
    "first_activity_seconds",
    "last_activity_seconds",
    "holding_seconds",
    "remaining_lots",
    "median_lot_age_seconds",
    "oldest_lot_age_seconds",
    "open",
    "entry_phase",
    "trade_count",
    "first_trade_seconds",
    "last_trade_seconds",
    "cross_wallet_trades",
)


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _read_receipts(
    store: ArtifactStore, relatives: Iterable[str]
) -> dict[str, RpcReceipt]:
    receipts: dict[str, RpcReceipt] = {}
    for relative in relatives:
        for receipt in read_list(store, relative, RpcReceipt, required=False):
            receipts.setdefault(receipt.transaction_hash, receipt)
    return receipts


def read_positions(store: ArtifactStore, minutes: int) -> dict[str, dict[str, Any]]:
    """Read the derived per-wallet position CSV into typed rows."""
    rows = store.read_csv(f"analysis/positions-{minutes}/positions.csv")
    if not rows:
        raise InvariantError(f"Position analysis produced no rows for {minutes}m")

    def optional(value: str | None) -> int | None:
        return int(value) if value not in (None, "") else None

    parsed = {}
    for row in rows:
        wallet = addr(row["wallet"])
        parsed[wallet] = {
            "tokens_end_raw": int(row["tokens_end_raw"]),
            "tokens_out_raw": int(row["tokens_out_raw"]),
            "realized_raw": int(row["realized_quote_raw"]),
            "unrealized_raw": optional(row["unrealized_quote_raw"]),
            "gas_raw": int(row["gas_quote_raw"]),
            "net_raw": optional(row["net_quote_raw"]),
            "cost_basis_raw": int(row["cost_basis_remaining_raw"]),
            "sold_basis_raw": optional(row.get("sold_basis_raw")),
            "sale_pnl_raw": optional(row.get("sale_pnl_raw")),
            "basis_deployed_raw": optional(row.get("basis_deployed_raw")),
            "realized_roi_bps": optional(row.get("realized_roi_bps")),
            "net_roi_bps": optional(row.get("net_roi_bps")),
            "holding_seconds": optional(row.get("holding_seconds")),
            "open": str(row.get("open", "")).lower() == "true",
            "entry_phase": row.get("entry_phase") or None,
            "trade_count": int(row["trade_count"]),
            "first_trade_seconds": optional(row.get("first_trade_seconds")),
            "last_trade_seconds": optional(row["last_trade_seconds"]),
        }
    return parsed


def _write(
    store: ArtifactStore,
    out: str,
    rows: list[dict[str, Any]],
    ledger: _Ledger,
    legs: list[TradeLeg],
    profile: Launch,
    receipts: dict[str, RpcReceipt],
    mark: dict[str, Any] | None,
    end: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    store.write_csv(f"{out}/positions.csv", rows, fields=POSITION_FIELDS)
    lot_rows = []
    for wallet in sorted(ledger.lots):
        for index, lot in enumerate(ledger.lots[wallet], start=1):
            mark_value = _mark_value(lot.tokens, mark)
            unrealized = mark_value - lot.cost if mark_value is not None else None
            lot_rows.append(
                {
                    "wallet": wallet,
                    "lot_index": index,
                    "tokens_raw": lot.tokens,
                    "tokens": from_wei(lot.tokens, profile.decimals),
                    "cost_raw": lot.cost,
                    "cost_eth": from_wei(lot.cost),
                    "acquired_timestamp": lot.timestamp,
                    "acquired_utc": utc(lot.timestamp),
                    "age_seconds": end - lot.timestamp,
                    "mark_value_raw": mark_value,
                    "mark_value_eth": _eth(mark_value),
                    "unrealized_pnl_raw": unrealized,
                    "unrealized_pnl_eth": _eth(unrealized),
                }
            )
    store.write_csv(
        f"{out}/lots.csv",
        lot_rows,
        fields=(
            "wallet",
            "lot_index",
            "tokens_raw",
            "tokens",
            "cost_raw",
            "cost_eth",
            "acquired_timestamp",
            "acquired_utc",
            "age_seconds",
            "mark_value_raw",
            "mark_value_eth",
            "unrealized_pnl_raw",
            "unrealized_pnl_eth",
        ),
    )
    leg_rows = [
        {
            "sequence": leg.sequence,
            "timestamp": leg.timestamp,
            "utc": utc(leg.timestamp),
            "seconds_after_migration": leg.timestamp - profile.start_timestamp,
            "block": leg.block,
            "tx_index": leg.tx_index,
            "log_index": leg.log_index,
            "tx_hash": leg.tx_hash,
            "phase": leg.phase,
            "side": leg.side,
            "token_wallet": leg.token_wallet,
            "quote_wallet": leg.quote_wallet,
            "funding_wallet": leg.funding_wallet,
            "resolved_intermediary": leg.resolved_intermediary or "",
            "tokens_raw": leg.tokens,
            "tokens": from_wei(leg.tokens, profile.decimals),
            "quote_gross_raw": leg.quote_gross,
            "quote_gross_eth": from_wei(leg.quote_gross),
            "quote_net_raw": leg.quote_net,
            "quote_net_eth": from_wei(leg.quote_net),
            "fee_quote_raw": leg.fee_quote,
            "tax_quote_raw": leg.tax_quote,
            "fee_token_raw": leg.fee_token,
            "tax_token_raw": leg.tax_token,
            "cross_wallet": leg.cross_wallet,
        }
        for leg in legs
    ]
    store.write_csv(
        f"{out}/trade_legs.csv",
        leg_rows,
        fields=(
            "sequence",
            "timestamp",
            "utc",
            "seconds_after_migration",
            "block",
            "tx_index",
            "log_index",
            "tx_hash",
            "phase",
            "side",
            "token_wallet",
            "quote_wallet",
            "funding_wallet",
            "resolved_intermediary",
            "tokens_raw",
            "tokens",
            "quote_gross_raw",
            "quote_gross_eth",
            "quote_net_raw",
            "quote_net_eth",
            "fee_quote_raw",
            "tax_quote_raw",
            "fee_token_raw",
            "tax_token_raw",
            "cross_wallet",
        ),
    )
    by_tx: dict[str, list[TradeLeg]] = {}
    for leg in legs:
        by_tx.setdefault(leg.tx_hash, []).append(leg)
    transaction_rows = []
    for tx_hash, tx_legs in sorted(
        by_tx.items(), key=lambda item: (item[1][0].timestamp, item[0])
    ):
        receipt = receipts.get(tx_hash)
        if receipt is None:
            raise InvariantError(f"Trade transaction {tx_hash} has no receipt")
        transaction_rows.append(
            {
                "tx_hash": tx_hash,
                "gas_payer": receipt.from_address,
                "gas_quote_raw": receipt.gas_cost,
                "gas_quote_eth": _eth(receipt.gas_cost),
                "legs": len(tx_legs),
                "buys": sum(leg.side == "buy" for leg in tx_legs),
                "sells": sum(leg.side == "sell" for leg in tx_legs),
                "token_wallets": len({leg.token_wallet for leg in tx_legs}),
                "resolved_intermediary_legs": sum(
                    leg.resolved_intermediary is not None for leg in tx_legs
                ),
                "cross_wallet_legs": sum(leg.cross_wallet for leg in tx_legs),
                "quote_gross_raw": sum(leg.quote_gross for leg in tx_legs),
                "quote_gross_eth": from_wei(sum(leg.quote_gross for leg in tx_legs)),
                "fee_quote_raw": sum(leg.fee_quote for leg in tx_legs),
                "tax_quote_raw": sum(leg.tax_quote for leg in tx_legs),
                "phases": ",".join(sorted({leg.phase for leg in tx_legs})),
                "first_timestamp": min(leg.timestamp for leg in tx_legs),
                "first_utc": utc(min(leg.timestamp for leg in tx_legs)),
                "last_timestamp": max(leg.timestamp for leg in tx_legs),
                "last_utc": utc(max(leg.timestamp for leg in tx_legs)),
            }
        )
    store.write_csv(
        f"{out}/transactions.csv",
        transaction_rows,
        fields=(
            "tx_hash",
            "gas_payer",
            "gas_quote_raw",
            "gas_quote_eth",
            "legs",
            "buys",
            "sells",
            "token_wallets",
            "resolved_intermediary_legs",
            "cross_wallet_legs",
            "quote_gross_raw",
            "quote_gross_eth",
            "fee_quote_raw",
            "tax_quote_raw",
            "phases",
            "first_timestamp",
            "first_utc",
            "last_timestamp",
            "last_utc",
        ),
    )
    return transaction_rows, lot_rows
