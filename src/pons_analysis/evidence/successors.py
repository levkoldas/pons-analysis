"""Descendant-wallet collection over the token transfer graph."""

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pons_analysis.core.errors import IncompleteHistory, InvariantError
from pons_analysis.core.evm import addr, position
from pons_analysis.core.models import Launch, RpcLog
from pons_analysis.providers.gmgn import GmgnProvider
from pons_analysis.providers.rpc import RpcProvider
from pons_analysis.storage.store import ArtifactStore

ZERO = "0x" + "0" * 40
DEAD = "0x" + "0" * 36 + "dead"


def hydrate_receipts(
    rpc: RpcProvider, store: ArtifactStore, logs: Iterable[RpcLog], relative: str
) -> list[dict[str, Any]]:
    hashes = sorted({log.transaction_hash for log in logs})
    with ThreadPoolExecutor(4) as workers:
        receipts = list(workers.map(rpc.receipt, hashes))
    heights = sorted({receipt.block_number for receipt in receipts})
    with ThreadPoolExecutor(4) as workers:
        blocks = list(workers.map(rpc.block, heights))
    timestamps = {block.number: block.timestamp for block in blocks}
    rows = []
    for receipt in receipts:
        if not receipt.succeeded:
            raise InvariantError("A mined event has a failed receipt")
        row = receipt.model_dump(mode="json", by_alias=True)
        row["block_timestamp"] = timestamps[receipt.block_number]
        rows.append(row)
    store.write_json(relative, rows)
    return rows


def collect_successors(
    rpc: RpcProvider,
    store: ArtifactStore,
    profile: Launch,
    *,
    start_block: int,
    wallets: Iterable[str],
    directory: str = "evidence/successors",
    max_generations: int = 20,
) -> dict[str, Any]:
    wallets = tuple(sorted({addr(wallet) for wallet in wallets}))
    bounds = store.read_json(f"{directory}/bounds.json")
    if bounds is None:
        tip = rpc.latest_block()
        bounds = {
            "start_block": start_block,
            "end_block": tip,
            "end_timestamp": rpc.block(tip).timestamp,
            "retrieved_at": time.time(),
        }
    if bounds["start_block"] != start_block:
        raise InvariantError("Existing snapshot has a different starting block")
    end = bounds["end_block"]
    done: set[str] = set()
    todo = set(wallets)
    events: dict[tuple[str, int], RpcLog] = {}
    excluded = {
        profile.curve,
        profile.manager,
        profile.router,
        profile.hook,
        profile.factory,
        ZERO,
        DEAD,
    }
    excluded.discard(None)
    generations = 0
    for _ in range(max_generations):
        if not todo:
            break
        generations += 1
        generation = sorted(todo)
        done.update(generation)
        todo = set()
        addresses = ["0x" + wallet[2:].rjust(64, "0") for wallet in generation]
        for topic_set in (
            [profile.transfer_topic, addresses],
            [profile.transfer_topic, None, addresses],
        ):
            for log in rpc.logs(profile.token, start_block, end, topic_set):
                events[(log.transaction_hash, log.log_index)] = log
        for log in events.values():
            source, recipient = addr(log.topics[1]), addr(log.topics[2])
            if source in done and recipient not in done | excluded:
                todo.add(recipient)
    if todo:
        raise InvariantError(
            f"Transfer graph exceeds {max_generations} generations; coverage is incomplete"
        )
    logs = sorted(events.values(), key=position)
    hydrate_receipts(rpc, store, logs, f"{directory}/receipts.json")
    store.write_json(f"{directory}/transfer_logs.json", logs)
    store.write_json(f"{directory}/tracked_wallets.json", sorted(done))
    store.write_json(f"{directory}/bounds.json", bounds)
    return {
        "wallets": len(done),
        "events": len(logs),
        "generations": generations,
        "bounds": bounds,
    }


def collect_wallet_activity(
    gmgn: GmgnProvider,
    store: ArtifactStore,
    *,
    wallets: Iterable[str],
    directory: str = "evidence/successors",
) -> dict[str, Any]:
    coverage = []
    for wallet in sorted({addr(item) for item in wallets}):
        history = gmgn.wallet_activity(wallet)
        if not history.complete:
            raise IncompleteHistory(history.model_dump())
        balance = gmgn.wallet_token_balance(wallet)
        store.write_json(f"{directory}/activities/{wallet}.json", history.items)
        store.write_json(f"{directory}/balances/{wallet}.json", balance)
        coverage.append(
            dict(wallet=wallet, pages=history.pages, activities=len(history.items))
        )
    store.write_json(f"{directory}/activity_coverage.json", coverage)
    return {"wallets": len(coverage), "coverage": coverage}
