"""Time-bucketed order flow and wallet net-flow attribution.

The position ledger's trade legs provide exact quote notional and side. This
engine aggregates them into UTC-aligned buckets and per-wallet net flow. Quote
notional is gross: curve buys include charged fees/taxes and v4 buys include
hook fees/tax where the ledger records them on the trade leg.
"""

import math
import statistics
from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.analytics.market.trajectory import percentile
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _int(value: Any) -> int:
    return int(value) if value not in (None, "") else 0


def _bucket_stats(
    events: list[dict[str, Any]],
    *,
    bucket_start: int,
    bucket_seconds: int,
    period_start: int,
    period_end: int,
) -> dict[str, Any]:
    buy = [event for event in events if event["side"] == "buy"]
    sell = [event for event in events if event["side"] == "sell"]
    buy_volume = sum(event["quote_raw"] for event in buy)
    sell_volume = sum(event["quote_raw"] for event in sell)
    volume = buy_volume + sell_volume
    sizes = sorted((event["quote_raw"] for event in events), reverse=True)
    top_count = max(1, math.ceil(len(sizes) * 0.1)) if sizes else 0
    top_volume = sum(sizes[:top_count]) if sizes else 0
    return {
        "bucket": bucket_start,
        "start_timestamp": bucket_start,
        "end_timestamp_exclusive": bucket_start + bucket_seconds,
        "start_utc": utc(bucket_start),
        "partial": bucket_start < period_start
        or bucket_start + bucket_seconds > period_end,
        "trades": len(events),
        "buys": len(buy),
        "sells": len(sell),
        "buy_volume_raw": buy_volume,
        "buy_volume_eth": from_wei(buy_volume),
        "sell_volume_raw": sell_volume,
        "sell_volume_eth": from_wei(sell_volume),
        "volume_raw": volume,
        "volume_eth": from_wei(volume),
        "net_flow_raw": buy_volume - sell_volume,
        "net_flow_eth": from_wei(buy_volume - sell_volume),
        "flow_imbalance_bps": (
            round((buy_volume - sell_volume) * 10_000 / volume) if volume else None
        ),
        "avg_trade_eth": from_wei(volume // len(events)) if events else None,
        "median_trade_eth": (
            from_wei(round(statistics.median(event["quote_raw"] for event in events)))
            if events
            else None
        ),
        "p90_trade_eth": (
            from_wei(percentile([event["quote_raw"] for event in events], 90))
            if events
            else None
        ),
        "max_trade_eth": from_wei(sizes[0]) if sizes else None,
        "top_decile_share_bps": (
            round(top_volume * 10_000 / volume) if volume else None
        ),
    }


BUCKET_FIELDS = (
    "bucket",
    "start_timestamp",
    "end_timestamp_exclusive",
    "start_utc",
    "partial",
    "trades",
    "buys",
    "sells",
    "buy_volume_raw",
    "buy_volume_eth",
    "sell_volume_raw",
    "sell_volume_eth",
    "volume_raw",
    "volume_eth",
    "net_flow_raw",
    "net_flow_eth",
    "flow_imbalance_bps",
    "avg_trade_eth",
    "median_trade_eth",
    "p90_trade_eth",
    "max_trade_eth",
    "top_decile_share_bps",
)

WALLET_FIELDS = (
    "wallet",
    "trades",
    "buy_trades",
    "sell_trades",
    "buy_volume_raw",
    "buy_volume_eth",
    "sell_volume_raw",
    "sell_volume_eth",
    "gross_volume_raw",
    "gross_volume_eth",
    "net_flow_raw",
    "net_flow_eth",
    "avg_trade_eth",
    "max_trade_eth",
)


def analyze_flow(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    bucket: int = 60,
    output: str | None = None,
) -> dict[str, Any]:
    """Aggregate trade legs into bucket and wallet order-flow tables."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if bucket < 1:
        raise ValueError("Flow bucket must be positive")
    path = f"analysis/positions-{minutes}/trade_legs.csv"
    if not store.exists(path):
        raise InvariantError(
            f"Missing flow evidence {path}; run analyze positions {minutes}"
        )
    period_end = profile.start_timestamp + minutes * 60
    events = []
    for row in store.read_csv(path):
        timestamp = _int(row["timestamp"])
        if timestamp < period_end:
            events.append(
                {
                    "timestamp": timestamp,
                    "side": row["side"],
                    "wallet": addr(row["token_wallet"]),
                    "quote_raw": _int(row["quote_gross_raw"]),
                }
            )
    if not events:
        raise InvariantError(f"No trade legs inside the {minutes}m window")
    events.sort(key=lambda event: event["timestamp"])
    period_start = min(profile.start_timestamp, events[0]["timestamp"])
    first_bucket = (period_start // bucket) * bucket
    last_bucket = ((period_end - 1) // bucket) * bucket
    by_bucket: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        bucket_start = (event["timestamp"] // bucket) * bucket
        by_bucket.setdefault(bucket_start, []).append(event)
    buckets = [
        _bucket_stats(
            by_bucket.get(bucket_start, []),
            bucket_start=bucket_start,
            bucket_seconds=bucket,
            period_start=period_start,
            period_end=period_end,
        )
        for bucket_start in range(first_bucket, last_bucket + 1, bucket)
    ]

    by_wallet: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_wallet.setdefault(event["wallet"], []).append(event)
    wallets = []
    for wallet, selected in by_wallet.items():
        buys = [event for event in selected if event["side"] == "buy"]
        sells = [event for event in selected if event["side"] == "sell"]
        buy_volume = sum(event["quote_raw"] for event in buys)
        sell_volume = sum(event["quote_raw"] for event in sells)
        gross = buy_volume + sell_volume
        wallets.append(
            {
                "wallet": wallet,
                "trades": len(selected),
                "buy_trades": len(buys),
                "sell_trades": len(sells),
                "buy_volume_raw": buy_volume,
                "buy_volume_eth": from_wei(buy_volume),
                "sell_volume_raw": sell_volume,
                "sell_volume_eth": from_wei(sell_volume),
                "gross_volume_raw": gross,
                "gross_volume_eth": from_wei(gross),
                "net_flow_raw": buy_volume - sell_volume,
                "net_flow_eth": from_wei(buy_volume - sell_volume),
                "avg_trade_eth": from_wei(gross // len(selected)),
                "max_trade_eth": from_wei(
                    max(event["quote_raw"] for event in selected)
                ),
            }
        )
    wallets.sort(key=lambda row: (-row["net_flow_raw"], row["wallet"]))
    buys = [event for event in events if event["side"] == "buy"]
    sells = [event for event in events if event["side"] == "sell"]
    buy_volume = sum(event["quote_raw"] for event in buys)
    sell_volume = sum(event["quote_raw"] for event in sells)
    volume = buy_volume + sell_volume
    sizes = sorted((event["quote_raw"] for event in events), reverse=True)
    top_count = max(1, math.ceil(len(sizes) * 0.1))
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "bucket_seconds": bucket,
        "bucket_alignment": "UTC epoch boundaries",
        "period_start_timestamp": period_start,
        "period_end_exclusive": period_end,
        "start_utc": utc(period_start),
        "end_utc": utc(period_end),
        "trades": len(events),
        "buys": len(buys),
        "sells": len(sells),
        "buy_volume_raw": buy_volume,
        "buy_volume_eth": from_wei(buy_volume),
        "sell_volume_raw": sell_volume,
        "sell_volume_eth": from_wei(sell_volume),
        "volume_raw": volume,
        "volume_eth": from_wei(volume),
        "net_flow_raw": buy_volume - sell_volume,
        "net_flow_eth": from_wei(buy_volume - sell_volume),
        "flow_imbalance_bps": (
            round((buy_volume - sell_volume) * 10_000 / volume) if volume else None
        ),
        "avg_trade_eth": from_wei(volume // len(events)),
        "median_trade_eth": from_wei(
            round(statistics.median(event["quote_raw"] for event in events))
        ),
        "p90_trade_eth": from_wei(
            percentile([event["quote_raw"] for event in events], 90)
        ),
        "max_trade_eth": from_wei(sizes[0]),
        "top_decile_share_bps": (
            round(sum(sizes[:top_count]) * 10_000 / volume) if volume else None
        ),
        "buckets": len(buckets),
        "partial_buckets": sum(row["partial"] for row in buckets),
        "rows_by_bucket": buckets,
        "top_buyers": sorted(
            (row for row in wallets if row["net_flow_raw"] > 0),
            key=lambda row: (-row["net_flow_raw"], row["wallet"]),
        )[:10],
        "top_sellers": sorted(
            (row for row in wallets if row["net_flow_raw"] < 0),
            key=lambda row: (row["net_flow_raw"], row["wallet"]),
        )[:10],
        "top_by_volume": sorted(
            buckets, key=lambda row: (-row["volume_raw"], row["bucket"])
        )[:10],
    }
    out = output or f"analysis/flow-{minutes}"
    store.write_csv(f"{out}/buckets.csv", buckets, fields=BUCKET_FIELDS)
    store.write_csv(f"{out}/wallets.csv", wallets, fields=WALLET_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
