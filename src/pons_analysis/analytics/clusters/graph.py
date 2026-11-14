"""Evidence-connected wallet clusters from trades, funding, and calldata.

Edges are deliberately literal: two wallets in the same trade transaction, a
native transfer between analyzed wallets, two wallets funded by the same
external address, or two wallets that submitted identical raw calldata.
Connected components are clusters of evidence, not proof of common ownership.
"""

import collections
import datetime
import statistics
from collections.abc import Iterable
from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.analytics.market.window import DEAD
from pons_analysis.analytics.positions import read_positions
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


class _DSU:
    def __init__(self, items: Iterable[str]):
        self.parent = {item: item for item in items}
        self.size = {item: 1 for item in items}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.size[left_root] < self.size[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.size[left_root] += self.size[right_root]


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def _int(value: str | int | None, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _timestamp(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    if text.isdigit():
        return int(text)
    try:
        return int(
            datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        )
    except ValueError as exc:
        raise InvariantError(f"Invalid edge timestamp: {text}") from exc


def _optional_sum(rows: list[dict[str, Any]], key: str) -> int | None:
    if not rows:
        return 0
    values = [row[key] for row in rows]
    if any(value is None for value in values):
        return None
    return sum(values)


def _pair_edge(
    kind: str,
    source: str,
    destination: str,
    *,
    tx: str = "",
    block: int = 0,
    timestamp: int = 0,
    value_raw: int = 0,
    value_eth: float = 0.0,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "type": kind,
        "source": source,
        "destination": destination,
        "tx": tx,
        "block": block,
        "timestamp": timestamp,
        "value_raw": value_raw,
        "value_eth": value_eth,
        "detail": detail,
    }


def _co_trade_edges(
    store: ArtifactStore,
    minutes: int,
    wallets: set[str],
    protocol: set[str],
) -> tuple[list[dict[str, Any]], int]:
    rows = store.read_csv(f"analysis/positions-{minutes}/trade_legs.csv")
    by_tx: dict[str, dict[str, Any]] = {}
    for row in rows:
        tx = row.get("tx_hash", "")
        if not tx:
            continue
        candidates = {row.get("token_wallet", "")}
        members = {
            addr(item)
            for item in candidates
            if item and addr(item) in wallets and addr(item) not in protocol
        }
        if not members:
            continue
        data = by_tx.setdefault(
            tx,
            {
                "members": set(),
                "block": _int(row.get("block")),
                "timestamp": _int(row.get("timestamp")),
            },
        )
        data["members"].update(members)
    edges = []
    multi_wallet_transactions = 0
    for tx, data in sorted(by_tx.items()):
        ordered_members = sorted(data["members"])
        if len(ordered_members) < 2:
            continue
        multi_wallet_transactions += 1
        for index, source in enumerate(ordered_members):
            for destination in ordered_members[index + 1 :]:
                edges.append(
                    _pair_edge(
                        "co_trade",
                        source,
                        destination,
                        tx=tx,
                        block=data["block"],
                        timestamp=data["timestamp"],
                        detail="same transaction",
                    )
                )
    return edges, multi_wallet_transactions


def _timing_edges(
    store: ArtifactStore,
    minutes: int,
    wallets: set[str],
    protocol: set[str],
    min_timing: int,
) -> tuple[list[dict[str, Any]], int]:
    rows = store.read_csv(f"analysis/positions-{minutes}/trade_legs.csv")
    by_block_side: dict[tuple[int, str], set[str]] = collections.defaultdict(set)
    for row in rows:
        wallet = addr(row.get("token_wallet", ""))
        if wallet not in wallets or wallet in protocol:
            continue
        by_block_side[(int(row["block"]), row.get("side", ""))].add(wallet)
    pairs: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    for (block, _side), members in by_block_side.items():
        ordered = sorted(members)
        for index, source in enumerate(ordered):
            for destination in ordered[index + 1 :]:
                pairs[(source, destination)].add(block)
    edges = []
    for (source, destination), blocks in sorted(pairs.items()):
        if len(blocks) < min_timing:
            continue
        edges.append(
            _pair_edge(
                "timing",
                source,
                destination,
                block=min(blocks),
                detail=f"{len(blocks)} same-block co-occurrences",
            )
        )
    return edges, len(edges)


def _round_trips(
    store: ArtifactStore,
    minutes: int,
    profile: Launch,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    rows = store.read_csv(f"analysis/positions-{minutes}/trade_legs.csv")
    by_wallet: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in rows:
        wallet = addr(row.get("token_wallet", ""))
        if wallet:
            by_wallet[wallet].append(row)
    trips: list[dict[str, Any]] = []
    behavior: dict[str, dict[str, Any]] = {}
    total_unmatched = 0
    for wallet, entries in sorted(by_wallet.items()):
        entries.sort(
            key=lambda row: (
                int(row["timestamp"]),
                int(row["block"]),
                int(row.get("tx_index") or 0),
                int(row["log_index"]),
            )
        )
        lots: collections.deque[list[Any]] = collections.deque()
        wallet_trips = []
        unmatched = 0
        for row in entries:
            tokens = int(row["tokens_raw"])
            quote = int(row["quote_net_raw"])
            timestamp = int(row["timestamp"])
            block = int(row["block"])
            if row.get("side") == "buy":
                if tokens > 0:
                    lots.append(
                        [tokens, quote, timestamp, block, row.get("tx_hash", "")]
                    )
                continue
            if tokens <= 0:
                continue
            remaining = tokens
            while remaining and lots:
                lot = lots[0]
                take = min(lot[0], remaining)
                cost = lot[1] * take // lot[0] if take < lot[0] else lot[1]
                proceeds = quote * take // tokens
                wallet_trips.append(
                    {
                        "wallet": wallet,
                        "entry_timestamp": lot[2],
                        "entry_utc": utc(lot[2]),
                        "entry_block": lot[3],
                        "entry_tx": lot[4],
                        "exit_timestamp": timestamp,
                        "exit_utc": utc(timestamp),
                        "exit_block": block,
                        "exit_tx": row.get("tx_hash", ""),
                        "hold_seconds": timestamp - lot[2],
                        "same_block": block == lot[3],
                        "tokens_raw": take,
                        "tokens": from_wei(take, profile.decimals),
                        "cost_raw": cost,
                        "cost_eth": _eth(cost),
                        "proceeds_raw": proceeds,
                        "proceeds_eth": _eth(proceeds),
                        "pnl_raw": proceeds - cost,
                        "pnl_eth": _eth(proceeds - cost),
                    }
                )
                if take < lot[0]:
                    lot[0] -= take
                    lot[1] -= cost
                else:
                    lots.popleft()
                remaining -= take
            if remaining:
                unmatched += remaining
        holds = [trip["hold_seconds"] for trip in wallet_trips]
        winning = sum(trip["pnl_raw"] > 0 for trip in wallet_trips)
        behavior[wallet] = {
            "round_trips": len(wallet_trips),
            "winning_round_trips": winning,
            "win_rate": winning / len(wallet_trips) if wallet_trips else None,
            "median_hold_seconds": statistics.median(holds) if holds else None,
            "same_block_round_trips": sum(trip["same_block"] for trip in wallet_trips),
            "trade_round_trip_pnl_raw": sum(trip["pnl_raw"] for trip in wallet_trips),
            "trade_round_trip_pnl_eth": _eth(
                sum(trip["pnl_raw"] for trip in wallet_trips)
            ),
            "unmatched_sell_tokens_raw": unmatched,
            "unmatched_sell_tokens": from_wei(unmatched, profile.decimals),
        }
        trips.extend(wallet_trips)
        total_unmatched += unmatched
    trips.sort(
        key=lambda trip: (
            trip["exit_timestamp"],
            trip["entry_timestamp"],
            trip["wallet"],
            trip["entry_tx"],
        )
    )
    all_holds = [trip["hold_seconds"] for trip in trips]
    totals = {
        "round_trips": len(trips),
        "winning_round_trips": sum(trip["pnl_raw"] > 0 for trip in trips),
        "win_rate": (
            sum(trip["pnl_raw"] > 0 for trip in trips) / len(trips) if trips else None
        ),
        "median_hold_seconds": statistics.median(all_holds) if all_holds else None,
        "same_block_round_trips": sum(trip["same_block"] for trip in trips),
        "trade_round_trip_pnl_raw": sum(trip["pnl_raw"] for trip in trips),
        "trade_round_trip_pnl_eth": _eth(sum(trip["pnl_raw"] for trip in trips)),
        "unmatched_sell_tokens_raw": total_unmatched,
        "unmatched_sell_tokens": from_wei(total_unmatched, profile.decimals),
    }
    return trips, behavior, totals


def _funding_edges(
    store: ArtifactStore,
    wallets: set[str],
    protocol: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = store.read_csv("analysis/funding/edges.csv")
    edges = []
    seen = set()
    by_source: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"destinations": set(), "value_raw": 0, "edges": 0}
    )
    for row in rows:
        source, destination = addr(row["source"]), addr(row["destination"])
        if source in protocol or destination in protocol:
            continue
        if destination not in wallets or source == destination:
            continue
        value_raw = _int(row.get("value_raw"))
        value_eth = float(row.get("value_eth") or 0.0)
        tx = row.get("tx", "")
        key = (source, destination, tx, value_raw)
        if key in seen:
            continue
        seen.add(key)
        if source in wallets:
            edges.append(
                _pair_edge(
                    "funding",
                    source,
                    destination,
                    tx=tx,
                    block=_int(row.get("block")),
                    timestamp=_timestamp(row.get("timestamp")),
                    value_raw=value_raw,
                    value_eth=value_eth,
                    detail=row.get("method") or row.get("kind") or "",
                )
            )
        data = by_source[source]
        data["destinations"].add(destination)
        data["value_raw"] += value_raw
        data["edges"] += 1
    groups = []
    for source, data in sorted(by_source.items()):
        if len(data["destinations"]) < 2:
            continue
        groups.append(
            {
                "source": source,
                "source_in_core": source in wallets,
                "members": sorted(data["destinations"]),
                "value_raw": data["value_raw"],
                "value_eth": from_wei(data["value_raw"]),
                "edges": data["edges"],
            }
        )
    return edges, groups


def _funding_metadata(
    store: ArtifactStore,
    wallets: set[str],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    names = store.directories("evidence/funding/wallets")
    if not names:
        return {}, [], 0
    meta_by_wallet: dict[str, dict[str, Any]] = {}
    by_calldata: dict[str, set[str]] = collections.defaultdict(set)
    funding_only = 0
    for name in names:
        wallet = addr(name)
        if wallet != name:
            raise InvariantError(f"Invalid funding wallet directory: {name}")
        relative = f"evidence/funding/wallets/{wallet}"
        meta = store.read_json(f"{relative}/meta.json")
        transactions = store.read_json(f"{relative}/transactions.json")
        if meta is None or transactions is None:
            raise InvariantError(f"Incomplete funding evidence for {wallet}")
        if wallet not in wallets:
            funding_only += 1
            continue
        meta_by_wallet[wallet] = meta
        for row in transactions:
            raw = str(row.get("raw_input") or row.get("input") or "").lower()
            if len(raw) < 10:
                continue
            by_calldata[raw].add(wallet)
    groups = []
    for raw, members in sorted(by_calldata.items()):
        if len(members) < 2:
            continue
        groups.append(
            {
                "selector": raw[:10],
                "bytes": (len(raw) - 2) // 2,
                "members": sorted(members),
                "wallets": len(members),
            }
        )
    return meta_by_wallet, groups, funding_only


def _calldata_edges(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for group in groups:
        members = group["members"]
        detail = f"{group['selector']} ({group['bytes']} bytes)"
        source = members[0]
        for destination in members[1:]:
            edges.append(
                _pair_edge(
                    "calldata",
                    source,
                    destination,
                    detail=detail,
                )
            )
    return edges


def _cluster_rows(
    clusters: list[list[str]],
    cluster_ids: dict[str, str],
    positions: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    shared_groups: list[dict[str, Any]],
    calldata_groups: list[dict[str, Any]],
    meta: dict[str, dict[str, Any]],
    behavior: dict[str, dict[str, Any]],
    trips: list[dict[str, Any]],
    fresh_nonce: int,
    profile: Launch,
) -> list[dict[str, Any]]:
    edge_counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for edge in edges:
        cluster = cluster_ids.get(edge["source"])
        if (
            cluster
            and edge["destination"] in cluster_ids
            and cluster_ids[edge["destination"]] == cluster
        ):
            edge_counts[cluster][edge["type"]] += 1
    shared_by_cluster: dict[str, set[str]] = collections.defaultdict(set)
    for group in shared_groups:
        clusters_touched = {
            cluster_ids[member] for member in group["members"] if member in cluster_ids
        }
        for cluster in clusters_touched:
            shared_by_cluster[cluster].add(group["source"])
    calldata_by_cluster: dict[str, int] = collections.Counter()
    for group in calldata_groups:
        clusters_touched = {
            cluster_ids[member] for member in group["members"] if member in cluster_ids
        }
        for cluster in clusters_touched:
            calldata_by_cluster[cluster] += 1

    rows = []
    for members, cluster_id in zip(
        clusters,
        (f"cluster-{index:03d}" for index in range(1, len(clusters) + 1)),
        strict=True,
    ):
        wallet_rows = [positions[wallet] for wallet in members if wallet in positions]
        if not wallet_rows:
            continue
        realized = sum(row["realized_raw"] for row in wallet_rows)
        unrealized = _optional_sum(wallet_rows, "unrealized_raw")
        gas = sum(row["gas_raw"] for row in wallet_rows)
        net = _optional_sum(wallet_rows, "net_raw")
        tokens_end = sum(row["tokens_end_raw"] for row in wallet_rows)
        cluster_trips = [trip for trip in trips if trip["wallet"] in members]
        cluster_holds = [trip["hold_seconds"] for trip in cluster_trips]
        winning = sum(trip["pnl_raw"] > 0 for trip in cluster_trips)
        unmatched = sum(
            behavior.get(wallet, {}).get("unmatched_sell_tokens_raw", 0)
            for wallet in members
        )
        rows.append(
            {
                "cluster_id": cluster_id,
                "wallets": len(members),
                "tokens_end_raw": tokens_end,
                "tokens_end": from_wei(tokens_end, profile.decimals),
                "realized_quote_raw": realized,
                "realized_quote_eth": _eth(realized),
                "unrealized_quote_raw": unrealized,
                "unrealized_quote_eth": _eth(unrealized),
                "gas_quote_raw": gas,
                "gas_quote_eth": _eth(gas),
                "net_quote_raw": net,
                "net_quote_eth": _eth(net),
                "co_trade_edges": edge_counts[cluster_id]["co_trade"],
                "timing_edges": edge_counts[cluster_id]["timing"],
                "funding_edges": edge_counts[cluster_id]["funding"],
                "calldata_edges": edge_counts[cluster_id]["calldata"],
                "shared_funders": len(shared_by_cluster[cluster_id]),
                "calldata_groups": calldata_by_cluster[cluster_id],
                "round_trips": len(cluster_trips),
                "winning_round_trips": winning,
                "win_rate": (winning / len(cluster_trips) if cluster_trips else None),
                "median_hold_seconds": (
                    statistics.median(cluster_holds) if cluster_holds else None
                ),
                "same_block_round_trips": sum(
                    trip["same_block"] for trip in cluster_trips
                ),
                "trade_round_trip_pnl_raw": sum(
                    trip["pnl_raw"] for trip in cluster_trips
                ),
                "trade_round_trip_pnl_eth": _eth(
                    sum(trip["pnl_raw"] for trip in cluster_trips)
                ),
                "unmatched_sell_tokens_raw": unmatched,
                "fresh_wallets": sum(
                    _int(meta.get(wallet, {}).get("nonce"), -1) <= fresh_nonce
                    for wallet in members
                    if wallet in meta
                ),
            }
        )
    return rows


def analyze_clusters(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    fresh_nonce: int = 10,
    min_timing: int = 3,
    output: str = "analysis/clusters",
) -> dict[str, Any]:
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    if fresh_nonce < 0:
        raise ValueError("Fresh-wallet nonce must be non-negative")
    if min_timing < 2:
        raise ValueError("Timing threshold must be at least two")
    positions = read_positions(store, minutes)
    wallets = set(positions)
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

    co_trade_edges, co_trade_transactions = _co_trade_edges(
        store, minutes, wallets, protocol
    )
    timing_edges, timing_pairs = _timing_edges(
        store, minutes, wallets, protocol, min_timing
    )
    funding_edges, shared_groups = _funding_edges(store, wallets, protocol)
    meta_by_wallet, calldata_groups, funding_only = _funding_metadata(store, wallets)
    calldata_edges = _calldata_edges(calldata_groups)
    edges = co_trade_edges + timing_edges + funding_edges + calldata_edges
    trips, behavior, round_trip_totals = _round_trips(store, minutes, profile)

    dsu = _DSU(wallets)
    for edge in edges:
        dsu.union(edge["source"], edge["destination"])
    for group in shared_groups:
        members = [member for member in group["members"] if member in wallets]
        for member in members[1:]:
            dsu.union(members[0], member)

    components: dict[str, list[str]] = collections.defaultdict(list)
    for wallet in wallets:
        components[dsu.find(wallet)].append(wallet)
    clusters = [sorted(members) for members in components.values() if len(members) > 1]
    clusters.sort(key=lambda members: (-len(members), members[0]))
    cluster_ids = {
        wallet: f"cluster-{index:03d}"
        for index, members in enumerate(clusters, start=1)
        for wallet in members
    }
    for edge in edges:
        cluster = cluster_ids.get(edge["source"])
        edge["cluster_id"] = (
            cluster
            if cluster and cluster_ids.get(edge["destination"]) == cluster
            else ""
        )
    edge_rows = sorted(
        edges,
        key=lambda edge: (
            edge["type"],
            edge["source"],
            edge["destination"],
            edge["tx"],
            edge["detail"],
        ),
    )
    cluster_rows = _cluster_rows(
        clusters,
        cluster_ids,
        positions,
        edges,
        shared_groups,
        calldata_groups,
        meta_by_wallet,
        behavior,
        trips,
        fresh_nonce,
        profile,
    )
    wallet_rows = []
    cluster_size_map = {
        f"cluster-{index:03d}": len(members)
        for index, members in enumerate(clusters, start=1)
    }
    for wallet in sorted(wallets):
        position = positions[wallet]
        cluster = cluster_ids.get(wallet, "")
        meta = meta_by_wallet.get(wallet)
        nonce = _int(meta.get("nonce")) if meta else None
        stats = behavior.get(wallet, {})
        wallet_rows.append(
            {
                "wallet": wallet,
                "cluster_id": cluster,
                "cluster_wallets": cluster_size_map.get(cluster, 1),
                "tokens_end_raw": position["tokens_end_raw"],
                "tokens_end": from_wei(position["tokens_end_raw"], profile.decimals),
                "realized_quote_raw": position["realized_raw"],
                "realized_quote_eth": _eth(position["realized_raw"]),
                "unrealized_quote_raw": position["unrealized_raw"],
                "unrealized_quote_eth": _eth(position["unrealized_raw"]),
                "gas_quote_raw": position["gas_raw"],
                "gas_quote_eth": _eth(position["gas_raw"]),
                "net_quote_raw": position["net_raw"],
                "net_quote_eth": _eth(position["net_raw"]),
                "nonce": nonce,
                "fresh": nonce is not None and nonce <= fresh_nonce,
                "is_contract": bool(meta.get("is_contract")) if meta else False,
                "round_trips": stats.get("round_trips", 0),
                "winning_round_trips": stats.get("winning_round_trips", 0),
                "win_rate": stats.get("win_rate"),
                "median_hold_seconds": stats.get("median_hold_seconds"),
                "same_block_round_trips": stats.get("same_block_round_trips", 0),
                "trade_round_trip_pnl_raw": stats.get("trade_round_trip_pnl_raw", 0),
                "trade_round_trip_pnl_eth": stats.get("trade_round_trip_pnl_eth"),
                "unmatched_sell_tokens_raw": stats.get("unmatched_sell_tokens_raw", 0),
            }
        )

    clustered_wallets = sum(len(members) for members in clusters)
    clustered_tokens = sum(
        positions[wallet]["tokens_end_raw"]
        for members in clusters
        for wallet in members
    )
    edge_type_counts = collections.Counter(edge["type"] for edge in edges)
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "method": "evidence-connected components",
        "method_note": "Links are observable evidence, not proof of common ownership.",
        "edge_types": {
            "co_trade": "both wallets appear as token holders in the same transaction",
            "timing": "two wallets traded in the same block on the same side repeatedly",
            "funding": "direct native transfer between analyzed wallets",
            "shared_funder": "an external address funded two or more analyzed wallets",
            "calldata": "identical full raw input in funding histories",
        },
        "wallets": len(wallets),
        "funding_wallets": len(meta_by_wallet),
        "funding_only_wallets": funding_only,
        "co_trade_transactions": co_trade_transactions,
        "min_timing": min_timing,
        "timing_pairs": timing_pairs,
        "clusters": len(clusters),
        "clustered_wallets": clustered_wallets,
        "singleton_wallets": len(wallets) - clustered_wallets,
        "largest_cluster": len(clusters[0]) if clusters else 0,
        "clustered_tokens_raw": clustered_tokens,
        "clustered_tokens": from_wei(clustered_tokens, profile.decimals),
        "edges": {
            "total": len(edges),
            **dict(sorted(edge_type_counts.items())),
        },
        "shared_funder_groups": len(shared_groups),
        "calldata_groups": len(calldata_groups),
        "fresh_nonce": fresh_nonce,
        "top_clusters": cluster_rows[:20],
        "shared_funders": shared_groups[:20],
        "calldata_groups_detail": calldata_groups[:20],
        "behavior": round_trip_totals,
        "top_round_trip_wallets": sorted(
            wallet_rows,
            key=lambda row: (
                -(row.get("trade_round_trip_pnl_raw") or 0),
                row["wallet"],
            ),
        )[:10],
    }
    store.write_csv(
        f"{output}/clusters.csv",
        cluster_rows,
        fields=(
            "cluster_id",
            "wallets",
            "tokens_end_raw",
            "tokens_end",
            "realized_quote_raw",
            "realized_quote_eth",
            "unrealized_quote_raw",
            "unrealized_quote_eth",
            "gas_quote_raw",
            "gas_quote_eth",
            "net_quote_raw",
            "net_quote_eth",
            "co_trade_edges",
            "timing_edges",
            "funding_edges",
            "calldata_edges",
            "shared_funders",
            "calldata_groups",
            "round_trips",
            "winning_round_trips",
            "win_rate",
            "median_hold_seconds",
            "same_block_round_trips",
            "trade_round_trip_pnl_raw",
            "trade_round_trip_pnl_eth",
            "unmatched_sell_tokens_raw",
            "fresh_wallets",
        ),
    )
    store.write_csv(
        f"{output}/wallets.csv",
        wallet_rows,
        fields=(
            "wallet",
            "cluster_id",
            "cluster_wallets",
            "tokens_end_raw",
            "tokens_end",
            "realized_quote_raw",
            "realized_quote_eth",
            "unrealized_quote_raw",
            "unrealized_quote_eth",
            "gas_quote_raw",
            "gas_quote_eth",
            "net_quote_raw",
            "net_quote_eth",
            "nonce",
            "fresh",
            "is_contract",
            "round_trips",
            "winning_round_trips",
            "win_rate",
            "median_hold_seconds",
            "same_block_round_trips",
            "trade_round_trip_pnl_raw",
            "trade_round_trip_pnl_eth",
            "unmatched_sell_tokens_raw",
        ),
    )
    store.write_csv(
        f"{output}/round_trips.csv",
        trips,
        fields=(
            "wallet",
            "entry_timestamp",
            "entry_utc",
            "entry_block",
            "entry_tx",
            "exit_timestamp",
            "exit_utc",
            "exit_block",
            "exit_tx",
            "hold_seconds",
            "same_block",
            "tokens_raw",
            "tokens",
            "cost_raw",
            "cost_eth",
            "proceeds_raw",
            "proceeds_eth",
            "pnl_raw",
            "pnl_eth",
        ),
    )
    store.write_csv(
        f"{output}/edges.csv",
        edge_rows,
        fields=(
            "type",
            "source",
            "destination",
            "tx",
            "block",
            "timestamp",
            "value_raw",
            "value_eth",
            "detail",
            "cluster_id",
        ),
    )
    store.write_json(f"{output}/summary.json", summary)
    return summary
