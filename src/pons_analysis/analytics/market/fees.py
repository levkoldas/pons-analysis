"""Protocol fee-schedule arithmetic and fee-burden attribution."""

from collections.abc import Iterable
from typing import Any

from pons_analysis.core.accounting.amm import Q96
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei, words
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def creator_entitlement(
    pending_fees: int, pending_tax: int = 0, *, creator_bps: int = 7000
) -> dict[str, int]:
    """Split pending quote fees and add the creator tax balance."""
    if not 0 <= creator_bps <= 10_000:
        raise ValueError("Creator share must be within 0..10000 basis points")
    if pending_fees < 0 or pending_tax < 0:
        raise ValueError("Fee balances must be non-negative")
    creator_share = pending_fees * creator_bps // 10_000
    return dict(
        creator=creator_share + pending_tax,
        protocol=pending_fees - creator_share,
    )


def escrow_balance(
    credits: int, claims: int, *, onchain: int | None = None, tolerance: int = 0
) -> int:
    """Reconcile escrow credits and claims, optionally against on-chain balance."""
    balance = credits - claims
    if onchain is not None and abs(balance - onchain) > tolerance:
        raise ValueError(f"Escrow ledger does not reconcile: {balance} != {onchain}")
    return balance


def pool_fees(
    logs: list[Any], *, hook: str, fee_topic: str, pool_id: str, token_word: int = 0
) -> int:
    """Sum hook ``FeeCollected`` amounts for one pool and currency word."""
    total = 0
    for log in logs:
        address = log["address"] if isinstance(log, dict) else log.address
        topics = log["topics"] if isinstance(log, dict) else log.topics
        if str(address).lower() != hook.lower():
            continue
        if not topics or str(topics[0]).lower() != fee_topic.lower():
            continue
        if len(topics) < 2 or str(topics[1]).lower() != pool_id.lower():
            continue
        values = words(log)
        if values and values[0] == token_word:
            total += sum(values[1:])
    return total


def _int(value: str | int | None, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _mark_value(amount: int, mark: dict[str, Any] | None) -> int | None:
    if amount == 0:
        return 0
    if not mark:
        return None
    sqrt_price = int(mark["sqrt_price_x96"])
    if sqrt_price <= 0:
        return None
    return amount * Q96 * Q96 // (sqrt_price * sqrt_price)


def _total_fee(row: dict[str, Any]) -> int | None:
    quote = row["fee_quote_raw"] + row["tax_quote_raw"]
    if not row["token_fee_raw"] and not row["token_tax_raw"]:
        return quote
    token_fee = row["token_fee_value_raw"]
    token_tax = row["token_tax_value_raw"]
    if token_fee is None or token_tax is None:
        return None
    return quote + token_fee + token_tax


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    volume = sum(row["volume_raw"] for row in rows)
    fee_quote = sum(row["fee_quote_raw"] for row in rows)
    tax_quote = sum(row["tax_quote_raw"] for row in rows)
    token_fee = sum(row["token_fee_raw"] for row in rows)
    token_tax = sum(row["token_tax_raw"] for row in rows)

    def optional_sum(key: str) -> int | None:
        values = [row[key] for row in rows]
        if any(value is None for value in values):
            return None
        return sum(values)

    token_fee_value = optional_sum("token_fee_value_raw")
    token_tax_value = optional_sum("token_tax_value_raw")
    totals = [_total_fee(row) for row in rows]
    total_fee = sum(totals) if all(value is not None for value in totals) else None
    burden = total_fee * 10_000 // volume if total_fee is not None and volume else None
    return {
        "trades": len(rows),
        "volume_raw": volume,
        "volume_eth": from_wei(volume),
        "fee_quote_raw": fee_quote,
        "fee_quote_eth": from_wei(fee_quote),
        "tax_quote_raw": tax_quote,
        "tax_quote_eth": from_wei(tax_quote),
        "token_fee_raw": token_fee,
        "token_tax_raw": token_tax,
        "token_fee_value_raw": token_fee_value,
        "token_fee_value_eth": _eth(token_fee_value),
        "token_tax_value_raw": token_tax_value,
        "token_tax_value_eth": _eth(token_tax_value),
        "total_fee_raw": total_fee,
        "total_fee_eth": _eth(total_fee),
        "fee_burden_bps": burden,
    }


def _groups(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    specs = [("all", "all")]
    specs.extend(("phase", value) for value in sorted({row["phase"] for row in rows}))
    specs.extend(("side", value) for value in sorted({row["side"] for row in rows}))
    specs.extend(
        sorted({("phase/side", f"{row['phase']}/{row['side']}") for row in rows})
    )
    groups = []
    for dimension, value in specs:
        selected = (
            rows
            if dimension == "all"
            else [
                row
                for row in rows
                if (
                    (dimension == "phase" and row["phase"] == value)
                    or (dimension == "side" and row["side"] == value)
                    or (
                        dimension == "phase/side"
                        and f"{row['phase']}/{row['side']}" == value
                    )
                )
            ]
        )
        group = _aggregate(selected)
        group["dimension"] = dimension
        group["value"] = value
        groups.append(group)
    return groups


def analyze_fees(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    out = output or f"analysis/fees-{minutes}"
    rows = store.read_csv(f"analysis/positions-{minutes}/trade_legs.csv")
    if not rows:
        raise InvariantError(
            f"Missing fee evidence analysis/positions-{minutes}/trade_legs.csv; "
            f"run analyze positions {minutes}"
        )
    positions = store.read_json(f"analysis/positions-{minutes}/summary.json") or {}
    mark = positions.get("mark")
    parsed = []
    for row in rows:
        fee_quote = _int(row.get("fee_quote_raw"))
        tax_quote = _int(row.get("tax_quote_raw"))
        token_fee = _int(row.get("fee_token_raw"))
        token_tax = _int(row.get("tax_token_raw"))
        parsed.append(
            {
                "wallet": addr(row["token_wallet"]),
                "phase": row.get("phase", ""),
                "side": row.get("side", ""),
                "volume_raw": _int(row.get("quote_gross_raw")),
                "fee_quote_raw": fee_quote,
                "tax_quote_raw": tax_quote,
                "token_fee_raw": token_fee,
                "token_tax_raw": token_tax,
                "token_fee_value_raw": _mark_value(token_fee, mark),
                "token_tax_value_raw": _mark_value(token_tax, mark),
            }
        )
    groups = _groups(parsed)
    by_wallet: dict[str, list[dict[str, Any]]] = {}
    for row in parsed:
        by_wallet.setdefault(row["wallet"], []).append(row)
    wallets = []
    for wallet in sorted(by_wallet):
        aggregate = _aggregate(by_wallet[wallet])
        aggregate["wallet"] = wallet
        wallets.append(aggregate)
    wallets.sort(
        key=lambda row: (
            -(row["total_fee_raw"] or 0),
            row["wallet"],
        )
    )
    totals = _aggregate(parsed)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "fee_scope": "fees charged to traders, not recipient allocation",
        "fee_quote_note": "curve fee_quote includes any snipe tax",
        "volume_basis": "gross quote leg",
        "token_fee_valuation": (
            "last observed v4 mark"
            if mark is not None
            else "unavailable; token-denominated fees cannot be valued"
        ),
        "mark": mark,
        "totals": totals,
        "groups": groups,
        "top_wallets": wallets[:20],
    }
    store.write_csv(
        f"{out}/groups.csv",
        groups,
        fields=(
            "dimension",
            "value",
            "trades",
            "volume_raw",
            "volume_eth",
            "fee_quote_raw",
            "fee_quote_eth",
            "tax_quote_raw",
            "tax_quote_eth",
            "token_fee_raw",
            "token_tax_raw",
            "token_fee_value_raw",
            "token_fee_value_eth",
            "token_tax_value_raw",
            "token_tax_value_eth",
            "total_fee_raw",
            "total_fee_eth",
            "fee_burden_bps",
        ),
    )
    store.write_csv(
        f"{out}/wallets.csv",
        wallets,
        fields=(
            "wallet",
            "trades",
            "volume_raw",
            "volume_eth",
            "fee_quote_raw",
            "fee_quote_eth",
            "tax_quote_raw",
            "tax_quote_eth",
            "token_fee_raw",
            "token_tax_raw",
            "token_fee_value_raw",
            "token_fee_value_eth",
            "token_tax_value_raw",
            "token_tax_value_eth",
            "total_fee_raw",
            "total_fee_eth",
            "fee_burden_bps",
        ),
    )
    store.write_json(f"{out}/summary.json", summary)
    return summary
