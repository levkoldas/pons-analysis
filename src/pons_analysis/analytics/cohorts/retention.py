"""Entry-cohort retention from replayed token balances.

Wallets are assigned to the UTC bucket where they first hold a positive
non-protocol balance. The engine then records token and holder retention for
each entry cohort at every subsequent bucket. Additional inflows can make token
retention exceed 100%; holder retention is the share of cohort wallets still
holding any tokens.
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


def _timeline_row(
    cohort_bucket: int,
    bucket: int,
    wallets: list[str],
    balances: collections.Counter[str],
    initial: dict[str, int],
    profile: Launch,
) -> dict[str, Any]:
    remaining = [wallet for wallet in wallets if balances[wallet] > 0]
    initial_tokens = sum(initial[wallet] for wallet in wallets)
    tokens_remaining = sum(balances[wallet] for wallet in remaining)
    return {
        "entry_bucket": cohort_bucket,
        "entry_utc": utc(cohort_bucket),
        "bucket": bucket,
        "bucket_utc": utc(bucket),
        "wallets": len(wallets),
        "wallets_remaining": len(remaining),
        "initial_tokens_raw": initial_tokens,
        "initial_tokens": from_wei(initial_tokens, profile.decimals),
        "tokens_remaining_raw": tokens_remaining,
        "tokens_remaining": from_wei(tokens_remaining, profile.decimals),
        "token_retention_bps": (
            tokens_remaining * 10_000 // initial_tokens if initial_tokens else None
        ),
        "holder_retention_bps": (
            len(remaining) * 10_000 // len(wallets) if wallets else None
        ),
    }


TIMELINE_FIELDS = (
    "entry_bucket",
    "entry_utc",
    "bucket",
    "bucket_utc",
    "wallets",
    "wallets_remaining",
    "initial_tokens_raw",
    "initial_tokens",
    "tokens_remaining_raw",
    "tokens_remaining",
    "token_retention_bps",
    "holder_retention_bps",
)

COHORT_FIELDS = (
    "entry_bucket",
    "entry_utc",
    "wallets",
    "wallets_remaining",
    "initial_tokens_raw",
    "initial_tokens",
    "tokens_remaining_raw",
    "tokens_remaining",
    "token_retention_bps",
    "holder_retention_bps",
)

WALLET_FIELDS = (
    "wallet",
    "entry_bucket",
    "entry_utc",
    "initial_tokens_raw",
    "initial_tokens",
    "tokens_end_raw",
    "tokens_end",
    "token_retention_bps",
    "open",
)


def analyze_retention(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    bucket: int = 60,
    output: str | None = None,
) -> dict[str, Any]:
    """Replay balances and measure entry-cohort retention over subsequent buckets."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if bucket < 1:
        raise ValueError("Retention bucket must be positive")
    window = f"evidence/windows/{minutes}"
    window_logs = read_list(store, f"{window}/token_logs.json", RpcLog)
    if profile.migration is None:
        transfers = window_logs
    else:
        cut = profile.migration.position()
        launch = read_list(store, "evidence/launch/transfers.json", RpcLog)
        transfers = [log for log in launch if log.position() <= cut] + [
            log for log in window_logs if log.position() > cut
        ]
    transfers.sort(key=position)
    if not transfers:
        raise InvariantError("No token transfers for retention analysis")
    if len({(log.transaction_hash, log.log_index) for log in transfers}) != len(
        transfers
    ):
        raise InvariantError("Duplicate token transfer in retention evidence")
    if any(
        log.address != profile.token
        or log.topics[:1] != [profile.transfer_topic]
        or log.removed
        for log in transfers
    ):
        raise InvariantError("Retention evidence contains an unexpected transfer")
    transfer_ledger(transfers)
    timestamps = read_blocks(
        store, ("evidence/launch/blocks.json", f"{window}/blocks.json")
    )
    period_end = profile.start_timestamp + minutes * 60
    events: list[tuple[int, RpcLog, int]] = []
    for log in transfers:
        timestamp = timestamps.get(log.block_number)
        if timestamp is None:
            raise InvariantError(
                f"Missing timestamp for retention block {log.block_number}"
            )
        if timestamp < period_end:
            events.append((timestamp, log, int(log.data, 16)))
    if not events:
        raise InvariantError(f"No retention transfers inside the {minutes}m window")
    period_start = min(profile.start_timestamp, events[0][0])
    first_bucket = (period_start // bucket) * bucket
    last_bucket = ((period_end - 1) // bucket) * bucket
    by_bucket: dict[int, list[tuple[RpcLog, int]]] = collections.defaultdict(list)
    for timestamp, log, amount in events:
        by_bucket[(timestamp // bucket) * bucket].append((log, amount))

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
    entry: dict[str, int] = {}
    initial: dict[str, int] = {}
    cohorts: dict[int, list[str]] = collections.defaultdict(list)
    timeline = []

    def record_entry(wallet: str, bucket_start: int) -> None:
        if wallet in entry or wallet in protocol or wallet == ZERO:
            return
        balance = balances[wallet]
        if balance <= 0:
            return
        entry[wallet] = bucket_start
        initial[wallet] = balance
        cohorts[bucket_start].append(wallet)

    for bucket_start in range(first_bucket, last_bucket + 1, bucket):
        for log, amount in by_bucket.get(bucket_start, []):
            source, destination = addr(log.topics[1]), addr(log.topics[2])
            balances[source] -= amount
            balances[destination] += amount
            record_entry(source, bucket_start)
            record_entry(destination, bucket_start)
        for wallet in balances:
            record_entry(wallet, bucket_start)
        for cohort_bucket, wallets in cohorts.items():
            if cohort_bucket <= bucket_start:
                timeline.append(
                    _timeline_row(
                        cohort_bucket,
                        bucket_start,
                        wallets,
                        balances,
                        initial,
                        profile,
                    )
                )
    last_bucket = max(row["bucket"] for row in timeline) if timeline else None
    cohorts_rows = []
    for cohort_bucket in sorted(cohorts):
        final = next(
            row
            for row in reversed(timeline)
            if row["entry_bucket"] == cohort_bucket and row["bucket"] == last_bucket
        )
        cohorts_rows.append(
            {
                "entry_bucket": cohort_bucket,
                "entry_utc": utc(cohort_bucket),
                "wallets": final["wallets"],
                "wallets_remaining": final["wallets_remaining"],
                "initial_tokens_raw": final["initial_tokens_raw"],
                "initial_tokens": final["initial_tokens"],
                "tokens_remaining_raw": final["tokens_remaining_raw"],
                "tokens_remaining": final["tokens_remaining"],
                "token_retention_bps": final["token_retention_bps"],
                "holder_retention_bps": final["holder_retention_bps"],
            }
        )
    wallets_rows = []
    for wallet, cohort_bucket in sorted(
        entry.items(), key=lambda item: (item[1], item[0])
    ):
        end = balances[wallet]
        wallets_rows.append(
            {
                "wallet": wallet,
                "entry_bucket": cohort_bucket,
                "entry_utc": utc(cohort_bucket),
                "initial_tokens_raw": initial[wallet],
                "initial_tokens": from_wei(initial[wallet], profile.decimals),
                "tokens_end_raw": end,
                "tokens_end": from_wei(end, profile.decimals),
                "token_retention_bps": (
                    end * 10_000 // initial[wallet] if initial[wallet] else None
                ),
                "open": end > 0,
            }
        )
    aggregate_initial = sum(initial.values())
    aggregate_end = sum(balances[wallet] for wallet in entry)
    wallets_remaining = sum(balances[wallet] > 0 for wallet in entry)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "bucket_seconds": bucket,
        "bucket_alignment": "UTC epoch boundaries",
        "period_start_timestamp": period_start,
        "period_end_exclusive": period_end,
        "start_utc": utc(period_start),
        "end_utc": utc(period_end),
        "cohorts": len(cohorts_rows),
        "wallets": len(entry),
        "wallets_remaining": wallets_remaining,
        "initial_tokens_raw": aggregate_initial,
        "initial_tokens": from_wei(aggregate_initial, profile.decimals),
        "tokens_remaining_raw": aggregate_end,
        "tokens_remaining": from_wei(aggregate_end, profile.decimals),
        "token_retention_bps": (
            aggregate_end * 10_000 // aggregate_initial if aggregate_initial else None
        ),
        "holder_retention_bps": (
            wallets_remaining * 10_000 // len(entry) if entry else None
        ),
        "rows": cohorts_rows,
        "top_by_retention": sorted(
            cohorts_rows,
            key=lambda row: (
                -(row["token_retention_bps"] or 0),
                row["entry_bucket"],
            ),
        )[:10],
    }
    out = output or f"analysis/retention-{minutes}"
    store.write_csv(f"{out}/timeline.csv", timeline, fields=TIMELINE_FIELDS)
    store.write_csv(f"{out}/cohorts.csv", cohorts_rows, fields=COHORT_FIELDS)
    store.write_csv(f"{out}/wallets.csv", wallets_rows, fields=WALLET_FIELDS)
    store.write_json(f"{out}/summary.json", summary)
    return summary
