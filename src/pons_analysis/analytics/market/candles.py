"""OHLCV candles, VWAP, realized volatility, and volume profile.

Candles aggregate the trajectory's presentation price series into UTC-aligned
time buckets. The trajectory price is the curve execution price or the v4
post-swap pool price. Volume is quote-denominated; VWAP uses quote volume over
token volume. The volume profile bins traded prices in log space so a launch
that spans orders of magnitude remains readable.
"""

import math
import statistics
from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore

PROFILE_BINS = 12


def _event(row: dict[str, str]) -> dict[str, Any] | None:
    price = float(row["price_eth"]) if row.get("price_eth") not in (None, "") else None
    if price is None or price <= 0:
        return None
    return {
        "timestamp": int(row["timestamp"]),
        "utc": row.get("utc", ""),
        "price": price,
        "quote_raw": int(row.get("quote_amount_raw") or 0),
        "token_raw": int(row.get("token_amount_raw") or 0),
        "side": row.get("side", ""),
    }


def _vwap(quote_raw: int, token_raw: int, decimals: int) -> float | None:
    if quote_raw <= 0 or token_raw <= 0:
        return None
    return from_wei(quote_raw) / from_wei(token_raw, decimals)


def _candles(
    events: list[dict[str, Any]],
    *,
    bucket_seconds: int,
    period_start: int,
    period_end: int,
    decimals: int,
    supply_tokens: float,
) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        if event["timestamp"] >= period_end:
            continue
        start = (event["timestamp"] // bucket_seconds) * bucket_seconds
        buckets.setdefault(start, []).append(event)
    rows = []
    for index, (start, selected) in enumerate(sorted(buckets.items()), start=1):
        prices = [event["price"] for event in selected]
        quote = sum(event["quote_raw"] for event in selected)
        token = sum(event["token_raw"] for event in selected)
        open_price = prices[0]
        close_price = prices[-1]
        high = max(prices)
        low = min(prices)
        rows.append(
            {
                "bucket": start,
                "bucket_index": index,
                "start_timestamp": start,
                "end_timestamp_exclusive": start + bucket_seconds,
                "start_utc": utc(start),
                "partial": start < period_start or start + bucket_seconds > period_end,
                "trades": len(selected),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "open_price_eth": open_price,
                "high_price_eth": high,
                "low_price_eth": low,
                "close_price_eth": close_price,
                "volume_raw": quote,
                "volume_eth": from_wei(quote),
                "buy_volume_raw": sum(
                    event["quote_raw"] for event in selected if event["side"] == "buy"
                ),
                "sell_volume_raw": sum(
                    event["quote_raw"] for event in selected if event["side"] == "sell"
                ),
                "vwap_eth": _vwap(quote, token, decimals),
                "fdv_eth": close_price * supply_tokens,
                "price_change_bps": (
                    round((close_price / open_price - 1) * 10_000)
                    if open_price > 0
                    else None
                ),
                "range_bps": round((high - low) / low * 10_000) if low > 0 else None,
            }
        )
    return rows


def _volume_profile(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priced = [
        event for event in events if event["price"] > 0 and event["quote_raw"] > 0
    ]
    if not priced:
        return []
    low = min(event["price"] for event in priced)
    high = max(event["price"] for event in priced)
    log_low = math.log10(low)
    log_high = math.log10(high)
    bins = PROFILE_BINS if log_high > log_low else 1
    buckets = [
        {"trades": 0, "volume_raw": 0, "volume_eth": 0.0, "buy_raw": 0, "sell_raw": 0}
        for _ in range(bins)
    ]
    for event in priced:
        if bins == 1:
            index = 0
        else:
            fraction = (math.log10(event["price"]) - log_low) / (log_high - log_low)
            index = min(bins - 1, max(0, int(fraction * bins)))
        bucket = buckets[index]
        bucket["trades"] += 1
        bucket["volume_raw"] += event["quote_raw"]
        bucket["volume_eth"] = from_wei(bucket["volume_raw"])
        if event["side"] == "buy":
            bucket["buy_raw"] += event["quote_raw"]
        elif event["side"] == "sell":
            bucket["sell_raw"] += event["quote_raw"]
    total = sum(bucket["volume_raw"] for bucket in buckets)
    rows = []
    for index, bucket in enumerate(buckets):
        if bins == 1:
            price_low = price_high = low
        else:
            price_low = 10 ** (log_low + (log_high - log_low) * index / bins)
            price_high = (
                high
                if index == bins - 1
                else 10 ** (log_low + (log_high - log_low) * (index + 1) / bins)
            )
        rows.append(
            {
                "bin": index + 1,
                "price_low_eth": price_low,
                "price_high_eth": price_high,
                "trades": bucket["trades"],
                "volume_raw": bucket["volume_raw"],
                "volume_eth": bucket["volume_eth"],
                "buy_volume_raw": bucket["buy_raw"],
                "sell_volume_raw": bucket["sell_raw"],
                "volume_share_bps": (
                    round(bucket["volume_raw"] * 10_000 / total) if total else 0
                ),
            }
        )
    if total:
        difference = 10_000 - sum(row["volume_share_bps"] for row in rows)
        if difference:
            largest = max(rows, key=lambda row: row["volume_raw"])
            largest["volume_share_bps"] += difference
    return rows


CANDLE_FIELDS = (
    "bucket",
    "bucket_index",
    "start_timestamp",
    "end_timestamp_exclusive",
    "start_utc",
    "partial",
    "trades",
    "open_price_eth",
    "high_price_eth",
    "low_price_eth",
    "close_price_eth",
    "volume_raw",
    "volume_eth",
    "buy_volume_raw",
    "sell_volume_raw",
    "vwap_eth",
    "fdv_eth",
    "price_change_bps",
    "range_bps",
)

PROFILE_FIELDS = (
    "bin",
    "price_low_eth",
    "price_high_eth",
    "trades",
    "volume_raw",
    "volume_eth",
    "buy_volume_raw",
    "sell_volume_raw",
    "volume_share_bps",
)


def analyze_candles(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    bucket: int = 60,
    output: str | None = None,
) -> dict[str, Any]:
    """Aggregate trajectory rows into UTC-aligned OHLCV candles and a profile."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if bucket < 1:
        raise ValueError("Candle bucket must be positive")
    path = f"analysis/trajectory-{minutes}/trajectory.csv"
    if not store.exists(path):
        raise InvariantError(
            f"Missing candle evidence {path}; run analyze trajectory {minutes}"
        )
    events = [
        event for row in store.read_csv(path) if (event := _event(row)) is not None
    ]
    if not events:
        raise InvariantError(
            f"No positive trajectory prices for {minutes}m; "
            f"run analyze trajectory {minutes}"
        )
    events.sort(key=lambda event: event["timestamp"])
    period_start = min(profile.start_timestamp, events[0]["timestamp"])
    period_end = profile.start_timestamp + minutes * 60
    events = [event for event in events if event["timestamp"] < period_end]
    if not events:
        raise InvariantError(
            f"No trajectory prices inside the {minutes}m window; "
            f"run analyze trajectory {minutes}"
        )
    candles = _candles(
        events,
        bucket_seconds=bucket,
        period_start=period_start,
        period_end=period_end,
        decimals=profile.decimals,
        supply_tokens=from_wei(profile.supply, profile.decimals),
    )
    total_quote = sum(event["quote_raw"] for event in events)
    total_token = sum(event["token_raw"] for event in events)
    closes = [row["close_price_eth"] for row in candles]
    returns = [
        math.log(closes[index] / closes[index - 1])
        for index in range(1, len(closes))
        if closes[index - 1] > 0 and closes[index] > 0
    ]
    volume_profile = _volume_profile(events)
    fdv_high = max(candles, key=lambda row: row["fdv_eth"]) if candles else None
    fdv_low = min(candles, key=lambda row: row["fdv_eth"]) if candles else None
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "bucket_seconds": bucket,
        "price_basis": (
            "trajectory price_eth: curve execution price; v4 post-swap pool price"
        ),
        "bucket_alignment": "UTC epoch boundaries",
        "period_start_timestamp": period_start,
        "period_end_exclusive": period_end,
        "start_utc": utc(period_start),
        "end_utc": utc(period_end),
        "trades": len(events),
        "candles": len(candles),
        "partial_candles": sum(row["partial"] for row in candles),
        "volume_raw": total_quote,
        "volume_eth": from_wei(total_quote),
        "buy_volume_raw": sum(
            event["quote_raw"] for event in events if event["side"] == "buy"
        ),
        "sell_volume_raw": sum(
            event["quote_raw"] for event in events if event["side"] == "sell"
        ),
        "vwap_eth": _vwap(total_quote, total_token, profile.decimals),
        "supply_tokens": from_wei(profile.supply, profile.decimals),
        "fdv_first_eth": candles[0]["fdv_eth"] if candles else None,
        "fdv_last_eth": candles[-1]["fdv_eth"] if candles else None,
        "fdv_peak_eth": fdv_high["fdv_eth"] if fdv_high else None,
        "fdv_peak_utc": fdv_high["start_utc"] if fdv_high else None,
        "fdv_low_eth": fdv_low["fdv_eth"] if fdv_low else None,
        "fdv_low_utc": fdv_low["start_utc"] if fdv_low else None,
        "first_price_eth": candles[0]["open_price_eth"] if candles else None,
        "last_price_eth": candles[-1]["close_price_eth"] if candles else None,
        "realized_volatility_bps": (
            round(statistics.pstdev(returns) * 10_000) if len(returns) > 1 else None
        ),
        "volatility_returns": len(returns),
        "max_range_bps": max((row["range_bps"] or 0 for row in candles), default=None),
        "volume_profile_bins": len(volume_profile),
        "volume_profile": volume_profile,
        "top_by_volume": sorted(
            candles, key=lambda row: (-row["volume_raw"], row["bucket"])
        )[:10],
    }
    out = output or f"analysis/candles-{minutes}"
    store.write_csv(f"{out}/candles.csv", candles, fields=CANDLE_FIELDS)
    store.write_csv(f"{out}/volume_profile.csv", volume_profile, fields=PROFILE_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
