"""Price, volume, and v4 virtual-reserve trajectory from observed trades.

The engine combines curve events with v4 swaps after migration. For every v4
swap it derives the post-state virtual reserves from ``liquidity`` and
``sqrtPriceX96`` and the implied pre-state by adding the swap's signed amount
deltas. Consecutive swaps must agree on that pre-state while liquidity is
unchanged; the first pre-state quote reserve is reconciled against the curve's
``CurveCompleted`` quote leg. All reserve and volume arithmetic stays integer;
floats appear only in presentation fields.
"""

import statistics
from collections.abc import Iterable
from typing import Any

from pons_analysis.analytics.common.artifacts import read_blocks, read_list, utc
from pons_analysis.core.accounting.amm import v4_price, v4_virtual_reserves
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import from_wei, position, sig, signed, words
from pons_analysis.core.models import Launch, RpcLog
from pons_analysis.storage.store import ArtifactStore

CURVE_BUY_TOPIC = sig("CurveBuy(address,address,uint256,uint256,uint256,uint256)")
CURVE_SELL_TOPIC = sig("CurveSell(address,address,uint256,uint256,uint256,uint256)")
CURVE_COMPLETED_TOPIC = sig("CurveCompleted(address,uint256,uint256)")
RESERVE_TOLERANCE = 1


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _price_eth(price_raw: float, decimals: int) -> float:
    return price_raw * 10**decimals / 10**18


def _execution_price(quote_raw: int, token_raw: int, decimals: int) -> float | None:
    if quote_raw <= 0 or token_raw <= 0:
        return None
    return from_wei(quote_raw) / from_wei(token_raw, decimals)


def _reserve_price(quote_raw: int, token_raw: int, decimals: int) -> float | None:
    if not token_raw:
        return None
    return from_wei(quote_raw) / from_wei(token_raw, decimals)


def _impact_bps(execution: float | None, pre: float | None) -> int | None:
    if execution is None or execution <= 0 or pre is None or pre <= 0:
        return None
    return round((execution / pre - 1) * 10_000)


def percentile(values: list[int], percent: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percent / 100)
    return ordered[min(len(ordered) - 1, max(0, index))]


def _sample(values: list[float], count: int = 80) -> list[float]:
    if len(values) <= count:
        return values
    if count == 1:
        return [values[-1]]
    step = (len(values) - 1) / (count - 1)
    return [values[round(index * step)] for index in range(count)]


def _curve_seed_quote(curve_logs: Iterable[RpcLog], profile: Launch) -> int | None:
    seed = None
    for log in curve_logs:
        if not log.topics or log.topics[0] != CURVE_COMPLETED_TOPIC:
            continue
        if profile.curve is not None and log.address != profile.curve:
            raise InvariantError("Curve evidence contains an unexpected contract")
        values = words(log)
        if len(values) < 3:
            raise InvariantError("CurveCompleted event is shorter than three words")
        seed = values[1]
    return seed


def _curve_events(
    curve_logs: Iterable[RpcLog],
    timestamps: dict[int, int],
    profile: Launch,
) -> list[dict[str, Any]]:
    events = []
    for log in curve_logs:
        if not log.topics:
            continue
        topic = log.topics[0]
        if topic not in (CURVE_BUY_TOPIC, CURVE_SELL_TOPIC):
            continue
        if profile.curve is not None and log.address != profile.curve:
            raise InvariantError("Curve evidence contains an unexpected contract")
        values = words(log)
        if len(values) < 4:
            raise InvariantError("Curve trade event is shorter than four words")
        timestamp = timestamps.get(log.block_number)
        if timestamp is None:
            raise InvariantError(
                f"Missing timestamp for curve block {log.block_number}"
            )
        if topic == CURVE_BUY_TOPIC:
            side = "buy"
            quote_raw, tokens_raw = values[0], values[1]
            fee_raw, tax_raw = values[2], values[3]
        else:
            side = "sell"
            tokens_raw, quote_raw = values[0], values[1]
            fee_raw, tax_raw = values[2], values[3]
        events.append(
            {
                "block": log.block_number,
                "tx_index": log.transaction_index,
                "log_index": log.log_index,
                "tx_hash": log.transaction_hash,
                "timestamp": timestamp,
                "utc": utc(timestamp),
                "seconds_after_migration": timestamp - profile.start_timestamp,
                "phase": "curve",
                "side": side,
                "token_amount_raw": tokens_raw,
                "quote_amount_raw": quote_raw,
                "fee_raw": fee_raw,
                "tax_raw": tax_raw,
                "execution_price_eth": _execution_price(
                    quote_raw, tokens_raw, profile.decimals
                ),
                "pool_price_eth_after": None,
                "pre_price_eth": None,
                "price_impact_bps": None,
                "price_impact_abs_bps": None,
                "sqrt_price_x96": None,
                "liquidity": None,
                "tick": None,
                "pre_quote_reserve_raw": None,
                "pre_token_reserve_raw": None,
                "quote_reserve_raw": None,
                "token_reserve_raw": None,
                "reserve_drift_quote_raw": None,
                "reserve_drift_token_raw": None,
                "liquidity_change": None,
            }
        )
    return events


def _v4_events(
    swaps: Iterable[RpcLog],
    timestamps: dict[int, int],
    profile: Launch,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events = []
    previous_post: tuple[int, int] | None = None
    previous_liquidity: int | None = None
    liquidity_changes = 0
    continuity_breaks = 0
    max_drift = 0
    first_pre_quote = None
    first_pre_token = None
    final_post = None
    mark = None

    for log in swaps:
        values = words(log)
        if len(values) < 6:
            raise InvariantError("V4 swap event is shorter than six words")
        amount0, amount1 = signed(values[0]), signed(values[1])
        if not (amount0 * amount1 <= 0 and amount1 != 0):
            raise InvariantError("V4 swap deltas do not cross zero")
        sqrt_price, liquidity = values[2], values[3]
        tick = signed(values[4] & 0xFFFFFF, bits=24)
        if sqrt_price <= 0:
            raise InvariantError("V4 sqrtPriceX96 must be positive")
        quote_reserve, token_reserve = v4_virtual_reserves(liquidity, sqrt_price)
        pre_quote = quote_reserve + amount0
        pre_token = token_reserve + amount1
        if pre_quote < 0 or pre_token < 0:
            raise InvariantError("V4 pre-swap reserves are negative")
        if first_pre_quote is None:
            first_pre_quote, first_pre_token = pre_quote, pre_token

        drift_quote = drift_token = None
        liquidity_change = (
            previous_liquidity is not None and liquidity != previous_liquidity
        )
        if liquidity_change:
            liquidity_changes += 1
        elif previous_post is not None:
            drift_quote = abs(pre_quote - previous_post[0])
            drift_token = abs(pre_token - previous_post[1])
            max_drift = max(max_drift, drift_quote, drift_token)
            if drift_quote > RESERVE_TOLERANCE or drift_token > RESERVE_TOLERANCE:
                continuity_breaks += 1

        timestamp = timestamps.get(log.block_number)
        if timestamp is None:
            raise InvariantError(f"Missing timestamp for swap block {log.block_number}")
        side = "buy" if amount1 > 0 else "sell"
        quote_raw = abs(amount0)
        tokens_raw = abs(amount1)
        price_raw = v4_price(sqrt_price)
        execution_price = _execution_price(quote_raw, tokens_raw, profile.decimals)
        pre_price = _reserve_price(pre_quote, pre_token, profile.decimals)
        impact = _impact_bps(execution_price, pre_price)
        events.append(
            {
                "block": log.block_number,
                "tx_index": log.transaction_index,
                "log_index": log.log_index,
                "tx_hash": log.transaction_hash,
                "timestamp": timestamp,
                "utc": utc(timestamp),
                "seconds_after_migration": timestamp - profile.start_timestamp,
                "phase": "v4",
                "side": side,
                "token_amount_raw": tokens_raw,
                "quote_amount_raw": quote_raw,
                "fee_raw": 0,
                "tax_raw": 0,
                "execution_price_eth": execution_price,
                "pool_price_eth_after": _price_eth(price_raw, profile.decimals),
                "pre_price_eth": pre_price,
                "price_impact_bps": impact,
                "price_impact_abs_bps": abs(impact) if impact is not None else None,
                "sqrt_price_x96": sqrt_price,
                "liquidity": liquidity,
                "tick": tick,
                "pre_quote_reserve_raw": pre_quote,
                "pre_token_reserve_raw": pre_token,
                "quote_reserve_raw": quote_reserve,
                "token_reserve_raw": token_reserve,
                "reserve_drift_quote_raw": drift_quote,
                "reserve_drift_token_raw": drift_token,
                "liquidity_change": liquidity_change,
            }
        )
        previous_post = (quote_reserve, token_reserve)
        previous_liquidity = liquidity
        final_post = (quote_reserve, token_reserve)
        mark = {
            "sqrt_price_x96": sqrt_price,
            "liquidity": liquidity,
            "tick": tick,
            "block": log.block_number,
            "timestamp": timestamp,
            "utc": utc(timestamp),
            "price_eth_per_token": _price_eth(price_raw, profile.decimals),
        }

    replay = {
        "available": bool(events),
        "initial_quote_raw": first_pre_quote,
        "initial_token_raw": first_pre_token,
        "final_quote_raw": final_post[0] if final_post else None,
        "final_token_raw": final_post[1] if final_post else None,
        "liquidity_changes": liquidity_changes,
        "continuity_breaks": continuity_breaks,
        "max_drift_raw": max_drift,
        "tolerance_raw": RESERVE_TOLERANCE,
    }
    return events, {"replay": replay, "mark": mark}


def _impact_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [event for event in events if event["price_impact_bps"] is not None]
    signed = [event["price_impact_bps"] for event in rows]
    absolute = [event["price_impact_abs_bps"] for event in rows]
    volume = sum(event["quote_amount_raw"] for event in rows)
    weighted = (
        sum(event["price_impact_abs_bps"] * event["quote_amount_raw"] for event in rows)
        / volume
        if volume
        else None
    )

    def side_stats(side: str) -> dict[str, Any]:
        selected = [event for event in rows if event["side"] == side]
        side_abs = [event["price_impact_abs_bps"] for event in selected]
        side_signed = [event["price_impact_bps"] for event in selected]
        side_volume = sum(event["quote_amount_raw"] for event in selected)
        return {
            "trades": len(selected),
            "volume_raw": side_volume,
            "volume_eth": from_wei(side_volume),
            "median_signed_bps": (
                round(statistics.median(side_signed)) if side_signed else None
            ),
            "median_abs_bps": (
                round(statistics.median(side_abs)) if side_abs else None
            ),
            "p90_abs_bps": percentile(side_abs, 90),
            "max_abs_bps": max(side_abs) if side_abs else None,
        }

    return {
        "scope": (
            "v4 only: execution price versus pre-swap virtual-reserve mid; "
            "includes pool fee and curvature; signed by trade direction"
        ),
        "trades": len(rows),
        "coverage_bps": (round(len(rows) * 10_000 / len(events)) if events else None),
        "median_signed_bps": round(statistics.median(signed)) if signed else None,
        "median_abs_bps": round(statistics.median(absolute)) if absolute else None,
        "p90_abs_bps": percentile(absolute, 90),
        "max_abs_bps": max(absolute) if absolute else None,
        "volume_weighted_abs_bps": round(weighted) if weighted is not None else None,
        "by_side": {
            "buy": side_stats("buy"),
            "sell": side_stats("sell"),
        },
        "top_by_impact": sorted(
            rows,
            key=lambda event: (
                -event["price_impact_abs_bps"],
                -event["quote_amount_raw"],
                event["block"],
                event["log_index"],
            ),
        )[:10],
    }


def analyze_trajectory(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    start = profile.start_timestamp
    end = start + minutes * 60
    window = f"evidence/windows/{minutes}"
    out = output or f"analysis/trajectory-{minutes}"

    if profile.migration is None:
        curve_logs = read_list(store, f"{window}/curve_logs.json", RpcLog)
        swaps = read_list(store, f"{window}/swaps_logs.json", RpcLog)
    else:
        cut = profile.migration.position()
        curve_logs = read_list(store, "evidence/launch/curve_logs.json", RpcLog)
        launch_swaps = [
            log
            for log in read_list(
                store, "evidence/launch/swaps.json", RpcLog, required=False
            )
            if log.position() <= cut
        ]
        window_swaps = [
            log
            for log in read_list(store, f"{window}/swaps_logs.json", RpcLog)
            if log.position() > cut
        ]
        swaps = launch_swaps + window_swaps
    swaps.sort(key=position)
    if len({(log.transaction_hash, log.log_index) for log in swaps}) != len(swaps):
        raise InvariantError("Duplicate V4 swap in trajectory evidence")
    for log in swaps:
        if log.address != profile.manager or log.topics[:2] != [
            profile.swap_topic,
            profile.pool_id,
        ]:
            raise InvariantError("V4 evidence contains an unexpected pool")

    timestamps = read_blocks(
        store, ("evidence/launch/blocks.json", f"{window}/blocks.json")
    )
    seed_quote = _curve_seed_quote(curve_logs, profile)
    curve_events = _curve_events(curve_logs, timestamps, profile)
    v4_events, v4_meta = _v4_events(swaps, timestamps, profile)
    events = curve_events + v4_events
    events.sort(
        key=lambda row: (
            row["block"],
            row["tx_index"],
            row["log_index"],
            0 if row["phase"] == "curve" else 1,
        )
    )

    cumulative = 0
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        cumulative += event["quote_amount_raw"]
        event["cumulative_volume_raw"] = cumulative
        event["cumulative_volume_eth"] = from_wei(cumulative)
        event["token_amount"] = from_wei(event["token_amount_raw"], profile.decimals)
        event["quote_amount"] = from_wei(event["quote_amount_raw"])
        event["price_eth"] = (
            event["pool_price_eth_after"]
            if event["phase"] == "v4"
            else event["execution_price_eth"]
        )

    prices = [event["price_eth"] for event in events if event["price_eth"] is not None]
    peak_event = max(
        (event for event in events if event["price_eth"] is not None),
        key=lambda event: event["price_eth"],
        default=None,
    )
    low_event = min(
        (event for event in events if event["price_eth"] is not None),
        key=lambda event: event["price_eth"],
        default=None,
    )
    max_drawdown_bps = 0
    if prices:
        running_peak = prices[0]
        max_drawdown = 0.0
        for price in prices:
            running_peak = max(running_peak, price)
            if running_peak:
                max_drawdown = max(max_drawdown, (running_peak - price) / running_peak)
        max_drawdown_bps = round(max_drawdown * 10_000)

    initial_quote = v4_meta["replay"]["initial_quote_raw"]
    seed_delta = (
        abs(initial_quote - seed_quote)
        if initial_quote is not None and seed_quote is not None
        else None
    )
    seed_reconciled = (
        seed_delta <= RESERVE_TOLERANCE if seed_delta is not None else None
    )
    replay = v4_meta["replay"]
    replay["curve_seed_quote_raw"] = seed_quote
    replay["seed_quote_delta_raw"] = seed_delta
    replay["seed_quote_reconciled"] = seed_reconciled
    replay["initial_quote_eth"] = _eth(replay["initial_quote_raw"])
    replay["initial_token_amount"] = (
        from_wei(replay["initial_token_raw"], profile.decimals)
        if replay["initial_token_raw"] is not None
        else None
    )
    replay["final_quote_eth"] = _eth(replay["final_quote_raw"])
    replay["final_token_amount"] = (
        from_wei(replay["final_token_raw"], profile.decimals)
        if replay["final_token_raw"] is not None
        else None
    )
    replay["curve_seed_quote_eth"] = _eth(seed_quote)
    replay["continuity_reconciled"] = (
        replay["continuity_breaks"] == 0 if replay["available"] else None
    )
    replay["reconciled"] = (
        replay["continuity_reconciled"] and seed_reconciled is not False
        if replay["available"]
        else None
    )

    total_volume = sum(event["quote_amount_raw"] for event in events)
    buy_volume = sum(
        event["quote_amount_raw"] for event in events if event["side"] == "buy"
    )
    sell_volume = sum(
        event["quote_amount_raw"] for event in events if event["side"] == "sell"
    )
    top_by_volume = sorted(events, key=lambda event: -event["quote_amount_raw"])[:20]
    impact = _impact_summary(v4_events)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "start_timestamp": start,
        "end_timestamp_exclusive": end,
        "start_utc": utc(start),
        "end_utc": utc(end),
        "price_unit": "ETH per whole token",
        "reserve_scope": "v4 virtual reserves",
        "decimals": profile.decimals,
        "trades": len(events),
        "curve_trades": len(curve_events),
        "v4_swaps": len(v4_events),
        "buys": sum(event["side"] == "buy" for event in events),
        "sells": sum(event["side"] == "sell" for event in events),
        "volume_raw": total_volume,
        "volume_eth": from_wei(total_volume),
        "buy_volume_raw": buy_volume,
        "buy_volume_eth": from_wei(buy_volume),
        "sell_volume_raw": sell_volume,
        "sell_volume_eth": from_wei(sell_volume),
        "first_price_eth": prices[0] if prices else None,
        "last_price_eth": prices[-1] if prices else None,
        "peak_price_eth": peak_event["price_eth"] if peak_event is not None else None,
        "peak_block": peak_event["block"] if peak_event is not None else None,
        "low_price_eth": low_event["price_eth"] if low_event is not None else None,
        "low_block": low_event["block"] if low_event is not None else None,
        "max_drawdown_bps": max_drawdown_bps,
        "execution_impact": impact,
        "reserve_replay": replay,
        "mark": v4_meta["mark"],
        "price_samples": _sample(prices),
        "top_by_volume": top_by_volume,
    }
    store.write_csv(
        f"{out}/trajectory.csv",
        events,
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
            "token_amount_raw",
            "token_amount",
            "quote_amount_raw",
            "quote_amount",
            "fee_raw",
            "tax_raw",
            "execution_price_eth",
            "pool_price_eth_after",
            "pre_price_eth",
            "price_impact_bps",
            "price_impact_abs_bps",
            "price_eth",
            "sqrt_price_x96",
            "liquidity",
            "tick",
            "pre_quote_reserve_raw",
            "pre_token_reserve_raw",
            "quote_reserve_raw",
            "token_reserve_raw",
            "reserve_drift_quote_raw",
            "reserve_drift_token_raw",
            "liquidity_change",
            "cumulative_volume_raw",
            "cumulative_volume_eth",
        ),
    )
    store.write_json(f"{out}/summary.json", summary)
    return summary
