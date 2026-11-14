"""Circulating-holder count and concentration timeline from token transfers.

The engine replays every non-protocol token balance through UTC-aligned buckets
and records holder count, top-1 and top-10 shares, and HHI. Protocol addresses
are excluded from holder metrics but retained in the replay so conservation
still holds. All balance arithmetic stays integer; percentages are presentation
fields.
"""

import collections
from typing import Any

from pons_analysis.analytics.common.artifacts import read_blocks, read_list, utc
from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.analytics.market.window import DEAD
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei, position
from pons_analysis.core.models import Launch, RpcLog
from pons_analysis.core.validation import transfer_ledger
from pons_analysis.storage.store import ArtifactStore


def _snapshot(
    bucket_start: int,
    bucket_seconds: int,
    period_start: int,
    period_end: int,
    balances: collections.Counter[str],
    protocol: set[str],
    previous: set[str],
    events: list[tuple[RpcLog, int]],
    profile: Launch,
) -> dict[str, Any]:
    holders = {
        wallet: balance
        for wallet, balance in balances.items()
        if balance > 0 and wallet not in protocol and wallet != ZERO
    }
    current = set(holders)
    values = sorted(holders.values(), reverse=True)
    total = sum(values)
    top1 = values[0] if values else 0
    top10 = sum(values[:10])
    hhi = (
        sum(value * value for value in values) * 10_000 // (total * total)
        if total
        else 0
    )
    moved = sum(int(log.data, 16) for log, _ in events)
    return {
        "bucket": bucket_start,
        "start_timestamp": bucket_start,
        "end_timestamp_exclusive": bucket_start + bucket_seconds,
        "start_utc": utc(bucket_start),
        "partial": bucket_start < period_start
        or bucket_start + bucket_seconds > period_end,
        "holders": len(holders),
        "new_holders": len(current - previous),
        "exited_holders": len(previous - current),
        "tokens_held_raw": total,
        "tokens_held": from_wei(total, profile.decimals),
        "top1_bps": top1 * 10_000 // total if total else None,
        "top10_bps": top10 * 10_000 // total if total else None,
        "hhi_bps": hhi if total else None,
        "transfers": len(events),
        "tokens_moved_raw": moved,
        "tokens_moved": from_wei(moved, profile.decimals),
    }


TIMELINE_FIELDS = (
    "bucket",
    "start_timestamp",
    "end_timestamp_exclusive",
    "start_utc",
    "partial",
    "holders",
    "new_holders",
    "exited_holders",
    "tokens_held_raw",
    "tokens_held",
    "top1_bps",
    "top10_bps",
    "hhi_bps",
    "transfers",
    "tokens_moved_raw",
    "tokens_moved",
)


def analyze_holders(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    bucket: int = 60,
    output: str | None = None,
) -> dict[str, Any]:
    """Build a holder-count and concentration timeline from raw token transfers."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if bucket < 1:
        raise ValueError("Holder bucket must be positive")
    window = f"evidence/windows/{minutes}"
    window_transfers = read_list(store, f"{window}/token_logs.json", RpcLog)
    if profile.migration is None:
        transfers = window_transfers
    else:
        cut = profile.migration.position()
        launch_transfers = read_list(store, "evidence/launch/transfers.json", RpcLog)
        transfers = [log for log in launch_transfers if log.position() <= cut] + [
            log for log in window_transfers if log.position() > cut
        ]
    transfers.sort(key=position)
    if len({(log.transaction_hash, log.log_index) for log in transfers}) != len(
        transfers
    ):
        raise InvariantError("Duplicate token transfer in holder evidence")
    if any(
        log.address != profile.token
        or log.topics[:1] != [profile.transfer_topic]
        or log.removed
        for log in transfers
    ):
        raise InvariantError("Holder evidence contains an unexpected transfer")
    if not transfers:
        raise InvariantError("No token transfers for holder analysis")
    transfer_ledger(transfers)
    timestamps = read_blocks(
        store, ("evidence/launch/blocks.json", f"{window}/blocks.json")
    )
    period_end = profile.start_timestamp + minutes * 60
    timed = []
    for log in transfers:
        timestamp = timestamps.get(log.block_number)
        if timestamp is None:
            raise InvariantError(
                f"Missing timestamp for holder block {log.block_number} "
                f"in {log.transaction_hash}"
            )
        if timestamp < period_end:
            timed.append((log, timestamp))
    if not timed:
        raise InvariantError(f"No token transfers inside the {minutes}m window")
    period_start = min(profile.start_timestamp, timed[0][1])
    first_bucket = (period_start // bucket) * bucket
    last_bucket = ((period_end - 1) // bucket) * bucket
    events_by_bucket: dict[int, list[tuple[RpcLog, int]]] = collections.defaultdict(
        list
    )
    for log, timestamp in timed:
        bucket_start = (timestamp // bucket) * bucket
        events_by_bucket[bucket_start].append((log, timestamp))

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
    balances: collections.Counter[str] = collections.Counter()
    previous: set[str] = set()
    timeline = []
    for bucket_start in range(first_bucket, last_bucket + 1, bucket):
        events = events_by_bucket.get(bucket_start, [])
        for log, _ in events:
            source, destination = addr(log.topics[1]), addr(log.topics[2])
            amount = int(log.data, 16)
            balances[source] -= amount
            balances[destination] += amount
        snapshot = _snapshot(
            bucket_start,
            bucket,
            period_start,
            period_end,
            balances,
            protocol,
            previous,
            events,
            profile,
        )
        snapshot["start_utc"] = utc(bucket_start)
        timeline.append(snapshot)
        previous = {
            wallet
            for wallet, balance in balances.items()
            if balance > 0 and wallet not in protocol and wallet != ZERO
        }

    peak = max(timeline, key=lambda row: (row["holders"], -row["start_timestamp"]))
    max_top1 = max(
        (row for row in timeline if row["top1_bps"] is not None),
        key=lambda row: (row["top1_bps"], -row["start_timestamp"]),
        default=None,
    )
    max_top10 = max(
        (row for row in timeline if row["top10_bps"] is not None),
        key=lambda row: (row["top10_bps"], -row["start_timestamp"]),
        default=None,
    )
    max_hhi = max(
        (row for row in timeline if row["hhi_bps"] is not None),
        key=lambda row: (row["hhi_bps"], -row["start_timestamp"]),
        default=None,
    )
    last = timeline[-1]
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "bucket_seconds": bucket,
        "bucket_alignment": "UTC epoch boundaries",
        "period_start_timestamp": period_start,
        "period_end_exclusive": period_end,
        "start_utc": utc(period_start),
        "end_utc": utc(period_end),
        "buckets": len(timeline),
        "transfers": len(timed),
        "first_holders": timeline[0]["holders"],
        "last_holders": last["holders"],
        "peak_holders": peak["holders"],
        "peak_utc": peak["start_utc"],
        "net_holder_change": last["holders"] - timeline[0]["holders"],
        "new_holders": sum(row["new_holders"] for row in timeline),
        "exited_holders": sum(row["exited_holders"] for row in timeline),
        "last_top1_bps": last["top1_bps"],
        "last_top10_bps": last["top10_bps"],
        "last_hhi_bps": last["hhi_bps"],
        "max_top1_bps": max_top1["top1_bps"] if max_top1 else None,
        "max_top1_utc": max_top1["start_utc"] if max_top1 else None,
        "max_top10_bps": max_top10["top10_bps"] if max_top10 else None,
        "max_top10_utc": max_top10["start_utc"] if max_top10 else None,
        "max_hhi_bps": max_hhi["hhi_bps"] if max_hhi else None,
        "max_hhi_utc": max_hhi["start_utc"] if max_hhi else None,
        "top_by_concentration": sorted(
            (row for row in timeline if row["top10_bps"] is not None),
            key=lambda row: (-row["top10_bps"], -row["top1_bps"], row["bucket"]),
        )[:10],
    }
    out = output or f"analysis/holders-{minutes}"
    store.write_csv(f"{out}/timeline.csv", timeline, fields=TIMELINE_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
