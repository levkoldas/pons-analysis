"""Exact wallet inventory and quote PnL from observed transfers and swaps.

The ledger replays every token transfer from the launch cut through a fixed
analysis window, attaches quote legs from bonding-curve and Uniswap-v4
swap events, and values remaining inventory at the last observed curve or pool
price. Cost basis is FIFO, the default rule when lots cannot be specifically
identified (IRS Publication 550). All accounting stays in integer token units
and wei; floats appear only in serialized presentation fields.

PnL is position-based: a quote leg follows the wallet that received or
delivered the tokens, so a router or hook that merely forwards a trade does not
own the resulting position. Cross-wallet funding follows matching token-transfer
paths through any number of intermediary routers and is labeled.
"""

import collections
from collections.abc import Iterable
from typing import Any

from pons_analysis.analytics.common.artifacts import read_blocks, read_list
from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.analytics.market.window import DEAD
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei, position, sig, signed, words
from pons_analysis.core.models import Launch, RpcLog, RpcReceipt
from pons_analysis.core.validation import reconcile_events, transfer_ledger
from pons_analysis.storage.store import ArtifactStore

from .artifacts import _eth, _read_receipts, _write
from .ledger import _add_lot, _move_lots, _reconcile, _take_lots
from .mark import _mark_price, _mark_value
from .matching import _match_transfer, _resolve_endpoint
from .models import TradeLeg, _Ledger
from .summary import _summary, median_int

CURVE_BUY_TOPIC = sig("CurveBuy(address,address,uint256,uint256,uint256,uint256)")
CURVE_SELL_TOPIC = sig("CurveSell(address,address,uint256,uint256,uint256,uint256)")
HOOK_FEE_TOPIC = sig("HookFeeCollected(bytes32,address,uint256,uint256)")


def _hook_fees(
    receipt: RpcReceipt, profile: Launch, swap_log: RpcLog
) -> tuple[int, int, int, int]:
    """Return hook fees belonging to one swap event.

    A transaction can contain multiple v4 swaps. Hook fee events are emitted
    after the swap that produced them, so attribute each fee event to the
    nearest preceding swap in the same pool instead of charging the whole
    receipt to every leg.
    """
    quote_fee = quote_tax = token_fee = token_tax = 0
    swaps = [
        log
        for log in receipt.logs
        if profile.swap_topic
        and log.topics
        and log.topics[0] == profile.swap_topic
        and len(log.topics) > 1
        and (profile.pool_id is None or log.topics[1] == profile.pool_id)
    ]
    for log in receipt.logs:
        if not log.topics or log.topics[0] != HOOK_FEE_TOPIC:
            continue
        if log.address != profile.hook:
            continue
        if len(log.topics) > 1 and profile.pool_id and log.topics[1] != profile.pool_id:
            continue
        preceding = [item for item in swaps if item.log_index < log.log_index]
        if not preceding:
            continue
        owner = max(preceding, key=lambda item: item.log_index)
        if owner.log_index != swap_log.log_index:
            continue
        values = words(log)
        if len(values) < 3:
            raise InvariantError("Hook fee event is shorter than its three words")
        currency = addr(values[0])
        if currency == ZERO:
            quote_fee += values[1]
            quote_tax += values[2]
        elif currency == profile.token:
            token_fee += values[1]
            token_tax += values[2]
    return quote_fee, quote_tax, token_fee, token_tax


def _leg_timestamp(
    receipt: RpcReceipt, block: int, timestamps: dict[int, int], tx_hash: str
) -> int:
    if receipt.block_timestamp is not None:
        return receipt.block_timestamp
    if block in timestamps:
        return timestamps[block]
    raise InvariantError(f"Missing timestamp for block {block} in {tx_hash}")


def _build_legs(
    profile: Launch,
    transfers: list[RpcLog],
    curve_logs: list[RpcLog],
    swaps: list[RpcLog],
    receipts: dict[str, RpcReceipt],
    timestamps: dict[int, int],
) -> tuple[list[TradeLeg], set[tuple[str, int]]]:
    protocol = {
        profile.curve,
        profile.manager,
        profile.router,
        profile.hook,
        profile.factory,
        ZERO,
        DEAD,
    }
    protocol.discard(None)
    bytx: dict[str, list[RpcLog]] = collections.defaultdict(list)
    outgoing: dict[tuple[str, str, int], list[tuple[str, RpcLog]]] = (
        collections.defaultdict(list)
    )
    incoming: dict[tuple[str, str, int], list[tuple[str, RpcLog]]] = (
        collections.defaultdict(list)
    )
    for log in transfers:
        bytx[log.transaction_hash].append(log)
        amount = int(log.data, 16)
        source, destination = addr(log.topics[1]), addr(log.topics[2])
        outgoing[(log.transaction_hash, source, amount)].append((destination, log))
        incoming[(log.transaction_hash, destination, amount)].append((source, log))

    legs: list[TradeLeg] = []
    skipped: set[tuple[str, int]] = set()

    def add(
        log: RpcLog,
        *,
        phase: str,
        side: str,
        token_wallet: str,
        quote_wallet: str,
        tokens: int,
        quote_gross: int,
        quote_net: int,
        fee_quote: int,
        tax_quote: int,
        fee_token: int,
        tax_token: int,
        hops: list[RpcLog],
        trade_leg: RpcLog,
    ) -> None:
        skipped.add((trade_leg.transaction_hash, trade_leg.log_index))
        for hop in hops:
            skipped.add((hop.transaction_hash, hop.log_index))
        if token_wallet == ZERO:
            return
        receipt = receipts.get(log.transaction_hash)
        if receipt is None:
            raise InvariantError(f"Missing receipt for trade {log.transaction_hash}")
        timestamp = _leg_timestamp(
            receipt, log.block_number, timestamps, log.transaction_hash
        )
        intermediary = None
        if hops:
            intermediary = addr(
                trade_leg.topics[2] if side == "buy" else trade_leg.topics[1]
            )
        legs.append(
            TradeLeg(
                block=log.block_number,
                tx_index=log.transaction_index,
                log_index=log.log_index,
                tx_hash=log.transaction_hash,
                timestamp=timestamp,
                phase=phase,
                side=side,
                token_wallet=token_wallet,
                quote_wallet=quote_wallet,
                funding_wallet=receipt.from_address,
                tokens=tokens,
                quote_gross=quote_gross,
                quote_net=quote_net,
                fee_quote=fee_quote,
                tax_quote=tax_quote,
                fee_token=fee_token,
                tax_token=tax_token,
                resolved_intermediary=intermediary,
                cross_wallet=(
                    intermediary is not None
                    or token_wallet != quote_wallet
                    or token_wallet != receipt.from_address
                ),
            )
        )

    for log in curve_logs:
        if log.topics[0] not in (CURVE_BUY_TOPIC, CURVE_SELL_TOPIC):
            continue
        values = words(log)
        if len(values) < 4:
            raise InvariantError("Curve trade event is shorter than four words")
        tx_logs = bytx[log.transaction_hash]
        if log.topics[0] == CURVE_BUY_TOPIC:
            buyer, recipient = addr(log.topics[1]), addr(log.topics[2])
            quote_gross, tokens, fee, tax = values[:4]
            trade_leg = _match_transfer(
                tx_logs, sender=profile.curve, recipient=recipient, amount=tokens
            )
            if trade_leg is None:
                raise InvariantError("Curve buy token leg is missing from transfers")
            token_wallet, hops = _resolve_endpoint(
                outgoing,
                incoming,
                trade_leg,
                side="buy",
                protocol=protocol,
                amount=tokens,
            )
            add(
                log,
                phase="curve",
                side="buy",
                token_wallet=token_wallet,
                quote_wallet=buyer,
                tokens=tokens,
                quote_gross=quote_gross,
                quote_net=quote_gross,
                fee_quote=fee,
                tax_quote=tax,
                fee_token=0,
                tax_token=0,
                hops=hops,
                trade_leg=trade_leg,
            )
        else:
            seller, recipient = addr(log.topics[1]), addr(log.topics[2])
            tokens, quote_net, fee, tax = values[:4]
            trade_leg = _match_transfer(
                tx_logs, sender=seller, recipient=profile.curve, amount=tokens
            )
            if trade_leg is None:
                raise InvariantError("Curve sell token leg is missing from transfers")
            token_wallet, hops = _resolve_endpoint(
                outgoing,
                incoming,
                trade_leg,
                side="sell",
                protocol=protocol,
                amount=tokens,
            )
            add(
                log,
                phase="curve",
                side="sell",
                token_wallet=token_wallet,
                quote_wallet=recipient,
                tokens=tokens,
                quote_gross=quote_net + fee + tax,
                quote_net=quote_net,
                fee_quote=fee,
                tax_quote=tax,
                fee_token=0,
                tax_token=0,
                hops=hops,
                trade_leg=trade_leg,
            )

    for log in swaps:
        values = words(log)
        if len(values) < 6:
            raise InvariantError("V4 swap event is shorter than six words")
        amount0, amount1 = signed(values[0]), signed(values[1])
        if not (amount0 * amount1 <= 0 and amount1 != 0):
            raise InvariantError("V4 swap deltas do not cross zero")
        side = "buy" if amount1 > 0 else "sell"
        tokens_gross = abs(amount1)
        tx_logs = bytx[log.transaction_hash]
        receipt = receipts.get(log.transaction_hash)
        if receipt is None:
            raise InvariantError(f"Missing receipt for swap {log.transaction_hash}")
        quote_fee, quote_tax, token_fee, token_tax = _hook_fees(receipt, profile, log)
        if side == "buy":
            expected = tokens_gross - token_fee - token_tax
            if expected < 0:
                raise InvariantError("V4 buy token fee exceeds pool output")
            trade_leg = _match_transfer(
                tx_logs, sender=profile.manager, amount=expected
            )
            if trade_leg is None:
                raise InvariantError("V4 buy token leg is missing from transfers")
            token_wallet, hops = _resolve_endpoint(
                outgoing,
                incoming,
                trade_leg,
                side="buy",
                protocol=protocol,
                amount=expected,
            )
            add(
                log,
                phase="v4",
                side="buy",
                token_wallet=token_wallet,
                quote_wallet=receipt.from_address,
                tokens=expected,
                quote_gross=abs(amount0) + quote_fee + quote_tax,
                quote_net=abs(amount0) + quote_fee + quote_tax,
                fee_quote=quote_fee,
                tax_quote=quote_tax,
                fee_token=token_fee,
                tax_token=token_tax,
                hops=hops,
                trade_leg=trade_leg,
            )
        else:
            trade_leg = _match_transfer(
                tx_logs, recipient=profile.manager, amount=tokens_gross
            )
            if trade_leg is None:
                raise InvariantError("V4 sell token leg is missing from transfers")
            token_wallet, hops = _resolve_endpoint(
                outgoing,
                incoming,
                trade_leg,
                side="sell",
                protocol=protocol,
                amount=tokens_gross,
            )
            add(
                log,
                phase="v4",
                side="sell",
                token_wallet=token_wallet,
                quote_wallet=token_wallet,
                tokens=tokens_gross,
                quote_gross=abs(amount0),
                quote_net=abs(amount0) - quote_fee - quote_tax,
                fee_quote=quote_fee,
                tax_quote=quote_tax,
                fee_token=token_fee,
                tax_token=token_tax,
                hops=hops,
                trade_leg=trade_leg,
            )
    legs.sort(key=TradeLeg.position)
    for sequence, leg in enumerate(legs, start=1):
        leg.sequence = sequence
    return legs, skipped


def _touch(stats: collections.Counter, timestamp: int, *, phase: str) -> None:
    if stats.get("first_activity_ts") is None:
        stats["entry_phase"] = phase
    first = stats.get("first_activity_ts")
    stats["first_activity_ts"] = timestamp if first is None else min(first, timestamp)
    last = stats.get("last_activity_ts")
    stats["last_activity_ts"] = timestamp if last is None else max(last, timestamp)


def _transfer_timestamp(timestamps: dict[int, int], log: RpcLog) -> int:
    timestamp = timestamps.get(log.block_number)
    if timestamp is None:
        raise InvariantError(
            f"Missing timestamp for transfer block {log.block_number} "
            f"in {log.transaction_hash}"
        )
    return timestamp


def _rows(
    ledger: _Ledger,
    balances: collections.Counter[str],
    protocol: set[str],
    cohort: set[str],
    profile: Launch,
    mark: dict[str, Any] | None,
    gas: collections.Counter[str],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    wallets = (
        set(ledger.lots)
        | set(ledger.stats)
        | {wallet for wallet, value in gas.items() if value}
        | {
            wallet
            for wallet, value in balances.items()
            if value and wallet not in protocol and wallet != ZERO
        }
    )
    rows = []
    for wallet in sorted(wallets):
        if wallet in protocol or wallet == ZERO:
            continue
        stats = ledger.stats[wallet]
        held = sum(lot.tokens for lot in ledger.lots.get(wallet, ()))
        bought = stats["bought_tokens"]
        sold = stats["sold_tokens"]
        transferred_in = stats["transfer_in"]
        transferred_out = stats["transfer_out"]
        external_in = stats["external_in"]
        external_out = stats["external_out"]
        realized = stats["realized"]
        gas_value = gas.get(wallet, 0)
        remaining_basis = sum(lot.cost for lot in ledger.lots.get(wallet, ()))
        market_value = _mark_value(held, mark)
        unrealized = (
            market_value - remaining_basis if market_value is not None else None
        )
        net = realized + unrealized - gas_value if unrealized is not None else None
        first = stats.get("first_trade_ts")
        last = stats.get("last_trade_ts")
        first_activity = stats.get("first_activity_ts")
        last_activity = stats.get("last_activity_ts")
        sold_basis = stats["sold_basis"]
        sale_pnl = stats["sale_pnl"]
        basis_deployed = sold_basis + remaining_basis
        roi_net = sale_pnl + unrealized - gas_value if unrealized is not None else None
        net_roi_bps = (
            round(roi_net * 10_000 / basis_deployed)
            if roi_net is not None and basis_deployed > 0
            else None
        )
        realized_roi_bps = (
            round(sale_pnl * 10_000 / sold_basis) if sold_basis > 0 else None
        )
        wallet_lots = ledger.lots.get(wallet, ())
        lot_ages = [max(0, end - lot.timestamp) for lot in wallet_lots]
        remaining_lots = len(wallet_lots)
        median_lot_age = median_int(lot_ages)
        oldest_lot_age = max(lot_ages) if lot_ages else None
        holding_seconds = None
        if first_activity is not None:
            holding_end = last_activity if held == 0 else end
            if holding_end is None:
                holding_end = end
            holding_seconds = max(0, holding_end - first_activity)
        real_total_in = bought + transferred_in + external_in
        real_total_out = sold + transferred_out + external_out
        if real_total_in - real_total_out != held:
            raise InvariantError(
                f"Position flow does not reconcile for {wallet}: "
                f"{real_total_in} in, {real_total_out} out, {held} held"
            )
        rows.append(
            {
                "wallet": wallet,
                "cohort": wallet in cohort,
                "tokens_end_raw": held,
                "tokens_end": from_wei(held, profile.decimals),
                "tokens_in_raw": real_total_in,
                "tokens_in": from_wei(real_total_in, profile.decimals),
                "tokens_out_raw": real_total_out,
                "tokens_out": from_wei(real_total_out, profile.decimals),
                "transfer_in_raw": transferred_in,
                "transfer_in": from_wei(transferred_in, profile.decimals),
                "transfer_out_raw": transferred_out,
                "transfer_out": from_wei(transferred_out, profile.decimals),
                "external_in_raw": external_in,
                "external_in": from_wei(external_in, profile.decimals),
                "external_out_raw": external_out,
                "external_out": from_wei(external_out, profile.decimals),
                "bought_tokens_raw": bought,
                "bought_tokens": from_wei(bought, profile.decimals),
                "sold_tokens_raw": sold,
                "sold_tokens": from_wei(sold, profile.decimals),
                "quote_spent_raw": stats["quote_spent"],
                "quote_spent_eth": _eth(stats["quote_spent"]),
                "quote_received_gross_raw": stats["quote_received_gross"],
                "quote_received_gross_eth": _eth(stats["quote_received_gross"]),
                "quote_received_net_raw": stats["quote_received_net"],
                "quote_received_net_eth": _eth(stats["quote_received_net"]),
                "fee_quote_raw": stats["fee_quote"],
                "tax_quote_raw": stats["tax_quote"],
                "token_fee_raw": stats["fee_token"],
                "token_tax_raw": stats["tax_token"],
                "realized_quote_raw": realized,
                "realized_quote_eth": _eth(realized),
                "unrealized_quote_raw": unrealized,
                "unrealized_quote_eth": _eth(unrealized),
                "gas_quote_raw": gas_value,
                "gas_quote_eth": _eth(gas_value),
                "net_quote_raw": net,
                "net_quote_eth": _eth(net),
                "cost_basis_remaining_raw": remaining_basis,
                "sold_basis_raw": sold_basis,
                "basis_deployed_raw": basis_deployed,
                "sale_pnl_raw": sale_pnl,
                "external_out_basis_raw": stats["external_out_basis"],
                "transfer_out_basis_raw": stats["transfer_out_basis"],
                "realized_roi_bps": realized_roi_bps,
                "net_roi_bps": net_roi_bps,
                "first_activity_seconds": (
                    (first_activity - start) if first_activity is not None else None
                ),
                "last_activity_seconds": (
                    (last_activity - start) if last_activity is not None else None
                ),
                "holding_seconds": holding_seconds,
                "remaining_lots": remaining_lots,
                "median_lot_age_seconds": median_lot_age,
                "oldest_lot_age_seconds": oldest_lot_age,
                "open": held > 0,
                "entry_phase": stats.get("entry_phase") or "unknown",
                "trade_count": stats["trade_count"],
                "first_trade_seconds": (first - start) if first is not None else None,
                "last_trade_seconds": (last - start) if last is not None else None,
                "cross_wallet_trades": stats["cross_wallet_trades"],
            }
        )
    rows.sort(key=lambda row: (-(row["net_quote_raw"] or 0), row["wallet"]))
    return rows


def analyze_positions(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    cohort: Iterable[str] = (),
    output: str | None = None,
) -> dict[str, Any]:
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    start = profile.start_timestamp
    end = start + minutes * 60
    window = f"evidence/windows/{minutes}"
    out = output or f"analysis/positions-{minutes}"

    window_transfers = read_list(store, f"{window}/token_logs.json", RpcLog)
    window_curve_logs = read_list(
        store, f"{window}/curve_logs.json", RpcLog, required=not profile.migrated
    )
    window_swaps = read_list(store, f"{window}/swaps_logs.json", RpcLog)
    if profile.migration is None:
        transfers = window_transfers
        curve_logs = window_curve_logs
        swaps = window_swaps
    else:
        cut = profile.migration.position()
        launch_transfers = read_list(store, "evidence/launch/transfers.json", RpcLog)
        transfers = [log for log in launch_transfers if log.position() <= cut] + [
            log for log in window_transfers if log.position() > cut
        ]
        curve_logs = [
            log
            for log in read_list(store, "evidence/launch/curve_logs.json", RpcLog)
            if log.position() <= cut
        ]
        launch_swaps = [
            log
            for log in read_list(store, "evidence/launch/swaps.json", RpcLog)
            if log.position() <= cut
        ]
        swaps = launch_swaps + [log for log in window_swaps if log.position() > cut]
    transfers.sort(key=position)
    if len({(log.transaction_hash, log.log_index) for log in transfers}) != len(
        transfers
    ):
        raise InvariantError("Duplicate token transfer in position evidence")
    if any(
        log.address != profile.token
        or log.topics[:1] != [profile.transfer_topic]
        or log.removed
        for log in transfers
    ):
        raise InvariantError("Position evidence contains an unexpected transfer")
    transfer_ledger(transfers)

    swaps.sort(key=position)
    if len({(log.transaction_hash, log.log_index) for log in swaps}) != len(swaps):
        raise InvariantError("Duplicate V4 swap in position evidence")
    event_legs = sum(
        log.topics[0] in (CURVE_BUY_TOPIC, CURVE_SELL_TOPIC) for log in curve_logs
    ) + len(swaps)
    for log in curve_logs:
        if log.address != profile.curve:
            raise InvariantError("Curve evidence contains an unexpected contract")
    for log in swaps:
        if log.address != profile.manager or log.topics[:2] != [
            profile.swap_topic,
            profile.pool_id,
        ]:
            raise InvariantError("V4 evidence contains an unexpected pool")

    timestamps = read_blocks(
        store, ("evidence/launch/blocks.json", f"{window}/blocks.json")
    )
    receipts = _read_receipts(
        store, ("evidence/launch/receipts.json", f"{window}/receipts.json")
    )
    reconcile_events(curve_logs + swaps, receipts.values())
    legs, skipped = _build_legs(
        profile, transfers, curve_logs, swaps, receipts, timestamps
    )
    gas: collections.Counter[str] = collections.Counter()
    for receipt in receipts.values():
        gas[receipt.from_address] += receipt.gas_cost

    protocol = {
        profile.curve,
        profile.manager,
        profile.router,
        profile.hook,
        profile.factory,
        ZERO,
        DEAD,
    }
    protocol.discard(None)
    cohort_set = {addr(item) for item in cohort}
    ledger = _Ledger()
    events: list[tuple[tuple[int, int, int, int], str, Any]] = []
    for log in transfers:
        if (log.transaction_hash, log.log_index) in skipped:
            continue
        events.append(((*log.position(), 0), "transfer", log))
    for leg in legs:
        events.append(((*leg.position(), 1), "trade", leg))
    events.sort(key=lambda item: item[0])

    balances: collections.Counter[str] = collections.Counter()
    for log in transfers:
        amount = int(log.data, 16)
        balances[addr(log.topics[1])] -= amount
        balances[addr(log.topics[2])] += amount

    for _, kind, item in events:
        if kind == "trade":
            leg: TradeLeg = item
            stats = ledger.stats[leg.token_wallet]
            _touch(stats, leg.timestamp, phase=leg.phase)
            stats["trade_count"] += 1
            first = stats.get("first_trade_ts")
            stats["first_trade_ts"] = (
                leg.timestamp if first is None else min(first, leg.timestamp)
            )
            last = stats.get("last_trade_ts")
            stats["last_trade_ts"] = (
                leg.timestamp if last is None else max(last, leg.timestamp)
            )
            stats["fee_quote"] += leg.fee_quote
            stats["tax_quote"] += leg.tax_quote
            stats["fee_token"] += leg.fee_token
            stats["tax_token"] += leg.tax_token
            if leg.side == "buy":
                _add_lot(
                    ledger, leg.token_wallet, leg.tokens, leg.quote_net, leg.timestamp
                )
                stats["bought_tokens"] += leg.tokens
                stats["quote_spent"] += leg.quote_net
            else:
                basis = _take_lots(
                    ledger,
                    leg.token_wallet,
                    leg.tokens,
                    context=leg.tx_hash,
                )
                stats["sold_tokens"] += leg.tokens
                stats["quote_received_gross"] += leg.quote_gross
                stats["quote_received_net"] += leg.quote_net
                stats["sold_basis"] += basis
                sale_pnl = leg.quote_net - basis
                stats["sale_pnl"] += sale_pnl
                stats["realized"] += sale_pnl
            if leg.cross_wallet:
                stats["cross_wallet_trades"] += 1
            continue

        log: RpcLog = item
        source, destination = addr(log.topics[1]), addr(log.topics[2])
        amount = int(log.data, 16)
        if source == ZERO:
            if destination not in protocol:
                timestamp = _transfer_timestamp(timestamps, log)
                _add_lot(ledger, destination, amount, 0, timestamp)
                ledger.stats[destination]["external_in"] += amount
                _touch(ledger.stats[destination], timestamp, phase="transfer")
            continue
        if source in protocol and destination in protocol:
            continue
        timestamp = _transfer_timestamp(timestamps, log)
        if source in protocol:
            _add_lot(ledger, destination, amount, 0, timestamp)
            ledger.stats[destination]["external_in"] += amount
            _touch(ledger.stats[destination], timestamp, phase="transfer")
        elif destination in protocol:
            basis = _take_lots(
                ledger,
                source,
                amount,
                context=f"transfer {log.transaction_hash}",
            )
            ledger.stats[source]["external_out"] += amount
            ledger.stats[source]["external_out_basis"] += basis
            ledger.stats[source]["realized"] -= basis
            _touch(ledger.stats[source], timestamp, phase="transfer")
        else:
            moved_basis = _move_lots(
                ledger,
                source,
                destination,
                amount,
                context=f"transfer {log.transaction_hash}",
            )
            ledger.stats[source]["transfer_out"] += amount
            ledger.stats[source]["transfer_out_basis"] += moved_basis
            ledger.stats[destination]["transfer_in"] += amount
            _touch(ledger.stats[source], timestamp, phase="transfer")
            _touch(ledger.stats[destination], timestamp, phase="transfer")

    _reconcile(balances, ledger.lots, ledger.available, protocol, profile)
    mark = _mark_price(swaps, timestamps, profile, curve_logs)
    rows = _rows(ledger, balances, protocol, cohort_set, profile, mark, gas, start, end)
    transaction_rows, lot_rows = _write(
        store, out, rows, ledger, legs, profile, receipts, mark, end
    )
    return _summary(
        store,
        out,
        rows,
        legs,
        balances,
        protocol,
        cohort_set,
        profile,
        mark,
        transactions=transaction_rows,
        lots=lot_rows,
        event_legs=event_legs,
        minutes=minutes,
        start=start,
        end=end,
    )
