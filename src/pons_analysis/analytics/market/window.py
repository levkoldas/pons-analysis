"""Analysis-window accounting over a fixed, profile-defined cut."""

import collections
import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.core.accounting.amm import v4_price_eth
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei, position, signed, words
from pons_analysis.core.models import Launch, RpcLog, RpcReceipt
from pons_analysis.core.validation import reconcile_events
from pons_analysis.storage.store import ArtifactStore

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEAD = "0x" + "0" * 36 + "dead"


def _block_timestamp(blocks: dict[int, int], block: int) -> int:
    timestamp = blocks.get(block)
    if timestamp is None:
        raise InvariantError(
            f"Transfer block {block} is missing from the window evidence"
        )
    return timestamp


@dataclass
class WindowResult:
    summary: dict[str, Any]
    trades: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    direct: list[dict[str, Any]]
    balances: dict[str, int]
    cohort: set[str]
    rates: list[tuple[int, float]]
    output: Path


def _utc(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.UTC).isoformat()


def _nearest(rates: list[tuple[int, float]], timestamp: int) -> float | None:
    if not rates:
        return None
    return min(rates, key=lambda row: abs(row[0] - timestamp))[1]


def _all_originals_empty(
    cohort: set[str],
    initial: collections.Counter[str],
    balances: collections.Counter[str],
    zero_times: dict[str, int],
    start: int,
) -> int | None:
    """Seconds until every original wallet is empty, or ``None`` if any remains."""
    if not cohort:
        return None
    empty_at: dict[str, int] = {}
    for wallet in cohort:
        if balances[wallet] != 0:
            return None
        if wallet in zero_times:
            empty_at[wallet] = zero_times[wallet]
        elif initial[wallet] == 0:
            empty_at[wallet] = start
        else:
            return None
    return max(empty_at.values()) - start


def analyze_window(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    cohort: Iterable[str] = (),
    output: str | None = None,
    return_details: bool = False,
):
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    start = profile.start_timestamp
    end = start + minutes * 60
    cut = profile.migration
    out = output or f"analysis/window-{minutes}"
    evidence = f"evidence/windows/{minutes}"

    def load_logs(name: str) -> list[RpcLog]:
        payload = store.read_json(f"{evidence}/{name}.json")
        if payload is None:
            raise InvariantError(f"Missing window artifact: {evidence}/{name}.json")
        return [RpcLog.model_validate(item) for item in payload]

    def load_receipts(path: str) -> list[RpcReceipt]:
        payload = store.read_json(path)
        if payload is None:
            raise InvariantError(f"Missing receipt artifact: {path}")
        return [RpcReceipt.model_validate(item) for item in payload]

    receipts = load_receipts(f"{evidence}/receipts.json")
    byhash = {receipt.transaction_hash: receipt for receipt in receipts}
    token_logs = sorted(load_logs("token_logs"), key=position)
    swaps = sorted(load_logs("swaps_logs"), key=position)
    if any(log.address != profile.token for log in token_logs):
        raise InvariantError("Token logs contain an unexpected contract")
    if any(
        log.address != profile.manager
        or log.topics[:2] != [profile.swap_topic, profile.pool_id]
        for log in swaps
    ):
        raise InvariantError("Swap logs contain an unexpected pool")
    reconcile_events(token_logs + swaps, receipts)

    swaps_by_tx = collections.defaultdict(list)
    for log in swaps:
        swaps_by_tx[log.transaction_hash].append(log)
    cut_position = cut.position() if cut is not None else None
    transfers = [
        log
        for log in token_logs
        if log.topics[0] == profile.transfer_topic
        and (cut_position is None or position(log) > cut_position)
    ]
    bytx = collections.defaultdict(list)
    for log in transfers:
        bytx[log.transaction_hash].append(log)

    blocks_payload = store.read_json(f"{evidence}/blocks.json") or {}
    blocks = {
        int(number): int(block["timestamp"], 16)
        if isinstance(block["timestamp"], str)
        else int(block["timestamp"])
        for number, block in blocks_payload.items()
    }
    cohort = {address.lower() for address in cohort}
    routes = []
    for tx_hash, logs in bytx.items():
        if cut_position is None:
            # Rotations are a post-migration router pattern.
            break
        incoming = [log for log in logs if addr(log.topics[2]) == profile.router]
        if not incoming:
            continue
        if len(incoming) != 1:
            raise InvariantError("Rotation transaction has ambiguous router input")
        log = incoming[0]
        outputs = [
            item
            for item in logs
            if addr(item.topics[1]) == profile.manager
            and addr(item.topics[2]) != profile.hook
        ]
        if not outputs:
            raise InvariantError("Rotation transaction has no manager payout")
        receipt = byhash[tx_hash]
        tx_swaps = swaps_by_tx[tx_hash]
        if not (
            len(tx_swaps) == 2
            and signed(words(tx_swaps[0])[0]) > 0
            and signed(words(tx_swaps[1])[0]) < 0
        ):
            raise InvariantError("Rotation transaction does not contain sell then buy")
        sell = words(tx_swaps[0])[0]
        buy = -signed(words(tx_swaps[1])[0])
        if sell == 0 or abs(buy / sell - 0.97) > 1e-9:
            raise InvariantError("Rotation value does not recycle 97% of gross")
        block = log.block_number
        timestamp = blocks.get(block)
        if timestamp is None:
            raise InvariantError(
                f"Rotation block {block} is missing from the window evidence"
            )
        routes.append(
            dict(
                timestamp=timestamp,
                seconds_after_migration=timestamp - start,
                block=block,
                tx_hash=tx_hash,
                source_wallet=addr(log.topics[1]),
                destination_wallet=addr(outputs[-1].topics[2]),
                sender=receipt.from_address,
                input_tokens_raw=str(int(log.data, 16)),
                received_tokens_raw=str(int(outputs[-1].data, 16)),
                sell_gross_raw=str(sell),
                rebuy_raw=str(buy),
                volume_raw=str(sell + buy),
                sell_fee_raw=str(sell - buy),
                input_tokens=int(log.data, 16) / 10**profile.decimals,
                received_tokens=int(outputs[-1].data, 16) / 10**profile.decimals,
                sell_gross_eth=from_wei(sell),
                rebuy_eth=from_wei(buy),
                volume_eth=from_wei(sell + buy),
                sell_fee_eth=from_wei(sell - buy),
            )
        )
    routes.sort(key=lambda row: (row["timestamp"], row["block"]))
    children = {row["destination_wallet"] for row in routes}
    rotations = {row["tx_hash"]: row for row in routes}

    linked = set(cohort) | children
    direct = []
    excluded = {profile.manager, profile.router, profile.hook, DEAD, ZERO}
    for log in transfers:
        source, destination = addr(log.topics[1]), addr(log.topics[2])
        if source in linked and destination not in excluded:
            linked.add(destination)
            direct.append(
                dict(
                    timestamp=_block_timestamp(blocks, log.block_number),
                    block=log.block_number,
                    source=source,
                    destination=destination,
                    tokens_raw=str(int(log.data, 16)),
                    tokens=int(log.data, 16) / 10**profile.decimals,
                    tx_hash=log.transaction_hash,
                )
            )

    activities = store.read_json(f"{evidence}/activities.json") or []
    actmap = collections.defaultdict(list)
    for activity in activities:
        if (
            activity.get("event_type") in ("buy", "sell")
            and start <= activity.get("timestamp", 0) < end
        ):
            actmap[(activity["tx_hash"], activity["event_type"])].append(activity)

    rates: list[tuple[int, float]] = []
    trade_rows = []
    for log in swaps:
        if cut_position is not None and position(log) <= cut_position:
            continue
        receipt = byhash[log.transaction_hash]
        timestamp = blocks.get(log.block_number)
        if timestamp is None:
            raise InvariantError("Swap block is missing from the window evidence")
        if not start <= timestamp < end:
            raise InvariantError("Swap receipt lies outside the requested window")
        amount0, amount1, sqrt_price, liquidity, _tick, fee = words(log)
        amount0, amount1 = signed(amount0), signed(amount1)
        if not (amount0 * amount1 <= 0 and amount1 != 0):
            raise InvariantError("Swap deltas do not cross zero")
        side = "buy" if amount1 > 0 else "sell"
        quote = abs(amount0)
        tokens = abs(amount1)
        quote_eth = from_wei(quote)
        matches = [
            activity
            for activity in actmap[(log.transaction_hash, side)]
            if activity.get("quote_amount") not in (None, "")
            and any(
                abs(float(activity["quote_amount"]) - quote_eth * factor)
                < max(1e-12, quote_eth * 1e-8)
                for factor in ([1, 0.97] if side == "buy" else [1])
            )
        ]
        unique = {
            (
                activity.get("tx_hash"),
                activity.get("event_type"),
                activity.get("token_amount"),
                activity.get("quote_amount"),
                activity.get("cost_usd"),
            ): activity
            for activity in matches
        }
        matches = list(unique.values())
        match = matches[0] if len(matches) == 1 else None
        if (
            match
            and float(match["quote_amount"]) > 0
            and match.get("cost_usd") is not None
        ):
            rates.append(
                (
                    timestamp,
                    float(match["cost_usd"]) / float(match["quote_amount"]),
                )
            )
        sold_sources = (
            [
                addr(item.topics[1])
                for item in bytx[log.transaction_hash]
                if addr(item.topics[2]) == profile.manager
                and abs(
                    int(item.data, 16) / 10**profile.decimals
                    - tokens / 10**profile.decimals
                )
                < max(1e-8, tokens / 10**profile.decimals * 1e-8)
            ]
            if side == "sell"
            else []
        )
        source = sold_sources[0] if len(sold_sources) == 1 else receipt.from_address
        owner = (
            rotations[log.transaction_hash]["source_wallet"]
            if log.transaction_hash in rotations
            else source
            if side == "sell"
            else receipt.from_address
        )
        category = (
            "cohort rotation"
            if log.transaction_hash in rotations
            else "original: direct sale"
            if side == "sell" and owner in cohort
            else "successor: direct sale"
            if side == "sell" and owner in children
            else "linked transfer recipient: sale"
            if side == "sell" and owner in linked
            else "other trading"
        )
        trade_rows.append(
            dict(
                sequence=len(trade_rows) + 1,
                timestamp=timestamp,
                utc=_utc(timestamp),
                seconds_after_migration=timestamp - start,
                block=log.block_number,
                tx_index=log.transaction_index,
                log_index=log.log_index,
                tx_hash=log.transaction_hash,
                sender=receipt.from_address,
                swap_sender=addr(log.topics[2]),
                side=side,
                token_amount_pool_raw=str(tokens),
                quote_raw=str(quote),
                token_amount_pool=tokens / 10**profile.decimals,
                quote_eth=quote_eth,
                pool_price_eth_after=v4_price_eth(sqrt_price, profile.decimals),
                pool_liquidity=liquidity,
                pool_fee=fee,
                inventory_owner=owner,
                category=category,
                gmgn_matched=match is not None,
                gmgn_volume_usd=(float(match.get("cost_usd") or 0) if match else None),
                gmgn_quote_eth=(
                    float(match["quote_amount"])
                    if match and match.get("quote_amount") is not None
                    else None
                ),
                gmgn_token_amount=(
                    float(match["token_amount"])
                    if match and match.get("token_amount") is not None
                    else None
                ),
            )
        )

    rates.sort()
    for trade in trade_rows:
        rate = _nearest(rates, trade["timestamp"])
        trade["eth_usd_reference"] = rate
        trade["pool_price_usd_after"] = (
            trade["pool_price_eth_after"] * rate if rate else None
        )
        trade["volume_usd"] = trade["quote_eth"] * rate if rate else None

    balances: collections.Counter[str] = collections.Counter()
    launch_receipts_payload = store.read_json("evidence/launch/receipts.json")
    initial_known = cut_position is not None and launch_receipts_payload is not None
    if cut_position is not None and launch_receipts_payload:
        for receipt in (
            RpcReceipt.model_validate(item) for item in launch_receipts_payload
        ):
            for log in receipt.logs:
                if (
                    log.address == profile.token
                    and log.topics[0] == profile.transfer_topic
                    and position(log) <= cut_position
                ):
                    amount = int(log.data, 16)
                    balances[addr(log.topics[1])] -= amount
                    balances[addr(log.topics[2])] += amount
    initial = balances.copy()
    zero_times: dict[str, int] = {}
    snapshots = []
    for log in transfers:
        source, destination = addr(log.topics[1]), addr(log.topics[2])
        amount = int(log.data, 16)
        balances[source] -= amount
        balances[destination] += amount
        if initial_known and balances[source] < 0 and source != ZERO:
            raise InvariantError(f"Negative token balance for {source}")
        timestamp = _block_timestamp(blocks, log.block_number)
        if source in cohort and balances[source] == 0:
            zero_times[source] = timestamp
        if source in linked or destination in linked:
            snapshots.append(
                dict(
                    timestamp=timestamp,
                    seconds_after_migration=timestamp - start,
                    original_tokens=sum(balances[wallet] for wallet in cohort)
                    / 10**profile.decimals,
                    successor_tokens=sum(balances[wallet] for wallet in children)
                    / 10**profile.decimals,
                    other_linked_tokens=sum(
                        balances[wallet] for wallet in linked - cohort - children
                    )
                    / 10**profile.decimals,
                )
            )

    wallets = []
    for wallet in sorted(cohort):
        sales = [
            trade
            for trade in trade_rows
            if trade["category"] == "original: direct sale"
            and trade["inventory_owner"] == wallet
        ]
        wallet_routes = [row for row in routes if row["source_wallet"] == wallet]
        wallet_direct = [row for row in direct if row["source"] == wallet]
        wallets.append(
            dict(
                wallet=wallet,
                tokens_at_migration=initial[wallet] / 10**profile.decimals,
                direct_sell_count=len(sales),
                direct_sold_tokens=sum(row["token_amount_pool"] for row in sales),
                direct_sell_eth=sum(row["quote_eth"] for row in sales),
                direct_sell_usd=sum(row["volume_usd"] or 0 for row in sales),
                first_sell_seconds=min(
                    (row["seconds_after_migration"] for row in sales), default=None
                ),
                last_sell_seconds=max(
                    (row["seconds_after_migration"] for row in sales), default=None
                ),
                rotation_count=len(wallet_routes),
                rotated_tokens=sum(row["input_tokens"] for row in wallet_routes),
                rotation_destinations=";".join(
                    row["destination_wallet"] for row in wallet_routes
                ),
                direct_transfer_tokens=sum(row["tokens"] for row in wallet_direct),
                direct_transfer_destinations=";".join(
                    row["destination"] for row in wallet_direct
                ),
                emptied_seconds=(
                    zero_times[wallet] - start
                    if wallet in zero_times and balances[wallet] == 0
                    else 0
                    if balances[wallet] == 0 and initial[wallet] == 0
                    else None
                ),
                balance_at_end=balances[wallet] / 10**profile.decimals,
            )
        )
    wallets.sort(
        key=lambda row: (
            row["emptied_seconds"] is None,
            row["emptied_seconds"] or 0,
        )
    )
    volume_by_tx: dict[str, Any] = {}
    successor_sales: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    rows_by_five_minutes: dict[int, list[dict[str, Any]]] = collections.defaultdict(
        list
    )
    for row in trade_rows:
        tx_hash = row["tx_hash"]
        volume_by_tx[tx_hash] = volume_by_tx.get(tx_hash, 0) + (row["volume_usd"] or 0)
        if row["category"] == "successor: direct sale":
            successor_sales[row["inventory_owner"]].append(row)
        rows_by_five_minutes[int(row["seconds_after_migration"]) // 300].append(row)

    for route in routes:
        route["volume_usd"] = volume_by_tx.get(route["tx_hash"], 0)
        route["destination_balance_end"] = (
            balances[route["destination_wallet"]] / 10**profile.decimals
        )
        sales = successor_sales.get(route["destination_wallet"], [])
        route["successor_sell_count"] = len(sales)
        route["successor_sold_tokens"] = sum(row["token_amount_pool"] for row in sales)
        route["successor_sell_usd"] = sum(row["volume_usd"] or 0 for row in sales)

    bins = []
    for index in range((minutes + 4) // 5):
        minute = index * 5
        rows = rows_by_five_minutes.get(index, [])
        bins.append(
            dict(
                minutes=f"{minute}-{min(minute + 5, minutes)}",
                trades=len(rows),
                buys=sum(row["side"] == "buy" for row in rows),
                sells=sum(row["side"] == "sell" for row in rows),
                buy_eth=sum(row["quote_eth"] for row in rows if row["side"] == "buy"),
                sell_eth=sum(row["quote_eth"] for row in rows if row["side"] == "sell"),
                volume_usd=sum(row["volume_usd"] or 0 for row in rows),
                first_price_usd=next(
                    (row["pool_price_usd_after"] for row in rows), None
                ),
                last_price_usd=rows[-1]["pool_price_usd_after"] if rows else None,
                rotation_volume_usd=sum(
                    row["volume_usd"] or 0
                    for row in rows
                    if row["category"] == "cohort rotation"
                ),
                linked_direct_sell_usd=sum(
                    row["volume_usd"] or 0
                    for row in rows
                    if row["category"]
                    in (
                        "original: direct sale",
                        "successor: direct sale",
                        "linked transfer recipient: sale",
                    )
                ),
            )
        )

    groups = []
    for category in sorted({row["category"] for row in trade_rows}):
        rows = [row for row in trade_rows if row["category"] == category]
        groups.append(
            dict(
                category=category,
                trades=len(rows),
                buys=sum(row["side"] == "buy" for row in rows),
                sells=sum(row["side"] == "sell" for row in rows),
                volume_eth=sum(row["quote_eth"] for row in rows),
                volume_usd=sum(row["volume_usd"] or 0 for row in rows),
            )
        )

    summary = dict(
        profile=profile.name,
        start_timestamp=start,
        end_timestamp_exclusive=end,
        swaps=len(trade_rows),
        transactions=len({row["tx_hash"] for row in trade_rows}),
        senders=len({row["sender"] for row in trade_rows}),
        buys=sum(row["side"] == "buy" for row in trade_rows),
        sells=sum(row["side"] == "sell" for row in trade_rows),
        gmgn_matched=sum(row["gmgn_matched"] for row in trade_rows),
        volume_eth=sum(row["quote_eth"] for row in trade_rows),
        volume_usd=sum(row["volume_usd"] or 0 for row in trade_rows),
        buy_eth=sum(row["quote_eth"] for row in trade_rows if row["side"] == "buy"),
        sell_eth=sum(row["quote_eth"] for row in trade_rows if row["side"] == "sell"),
        first_price_usd_after=trade_rows[0]["pool_price_usd_after"]
        if trade_rows
        else None,
        last_price_usd_after=trade_rows[-1]["pool_price_usd_after"]
        if trade_rows
        else None,
        peak_trade=max(
            trade_rows, key=lambda row: row["pool_price_eth_after"], default=None
        ),
        low_trade=min(
            trade_rows, key=lambda row: row["pool_price_eth_after"], default=None
        ),
        original_initial_tokens=sum(initial[wallet] for wallet in cohort)
        / 10**profile.decimals,
        original_final_tokens=sum(balances[wallet] for wallet in cohort)
        / 10**profile.decimals,
        successors_final_tokens=sum(balances[wallet] for wallet in children)
        / 10**profile.decimals,
        other_linked_final_tokens=sum(
            balances[wallet] for wallet in linked - cohort - children
        )
        / 10**profile.decimals,
        original_selling_wallets=sum(row["direct_sell_count"] > 0 for row in wallets),
        rotating_original_wallets=len({row["source_wallet"] for row in routes}),
        rotation_count=len(routes),
        rotation_first_seconds=routes[0]["seconds_after_migration"] if routes else None,
        rotation_last_seconds=routes[-1]["seconds_after_migration"] if routes else None,
        rotation_intervals=[
            b["timestamp"] - a["timestamp"] for a, b in pairwise(routes)
        ],
        rotated_tokens=sum(row["input_tokens"] for row in routes),
        rotation_received_tokens=sum(row["received_tokens"] for row in routes),
        all_originals_empty_seconds=_all_originals_empty(
            cohort, initial, balances, zero_times, start
        ),
        groups=groups,
        bins=bins,
        direct_transfers=direct,
    )
    store.write_csv(f"{out}/original_wallets.csv", wallets)
    store.write_csv(f"{out}/rotations.csv", routes)
    store.write_csv(f"{out}/cohort_holdings_timeline.csv", snapshots)
    store.write_csv(f"{out}/five_minute_summary.csv", bins)
    store.write_json(f"{out}/summary.json", summary)
    if return_details:
        return WindowResult(
            summary=summary,
            trades=trade_rows,
            routes=routes,
            direct=direct,
            balances=dict(balances),
            cohort=cohort,
            rates=rates,
            output=store.path(out),
        )
    return summary
