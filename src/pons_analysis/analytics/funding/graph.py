"""Native-ETH funding graphs and wallet flow statements."""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from pons_analysis.analytics.common.ethflow import (
    dedupe_internal_transfers,
    flow_statement,
)
from pons_analysis.analytics.market.launch import ZERO
from pons_analysis.analytics.market.window import DEAD
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei
from pons_analysis.core.models import Launch
from pons_analysis.core.rows import row_hash as _row_hash
from pons_analysis.core.rows import row_int as _row_int
from pons_analysis.storage.store import ArtifactStore


def _party(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("hash")
    return (value or "").lower()


def _value(row: Any) -> int:
    raw = row.get("value") if isinstance(row, dict) else getattr(row, "value", 0)
    if isinstance(raw, str):
        return int(raw, 16) if raw.startswith("0x") else int(raw)
    return int(raw or 0)


def _status(row: Any) -> bool:
    if isinstance(row, dict):
        if "result" in row:
            return str(row["result"]).lower() in ("success", "ok")
        if "success" in row:
            return bool(row["success"])
        status = row.get("status")
        return status in (1, "0x1", "1", True, "ok", "success")
    status = getattr(row, "status", None)
    return status in (1, "0x1", "1", True)


def native_edges(
    histories: dict[str, Iterable[Any]],
    *,
    exclude: Iterable[str] = (),
    is_contract: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Build deduplicated direct native-value edges from many wallet histories."""
    excluded = {addr(item) for item in exclude}
    unique: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    for wallet, rows in histories.items():
        wallet = addr(wallet)
        for row in rows:
            if not _status(row):
                continue
            if isinstance(row, dict):
                sender = _party(row.get("from"))
                recipient = _party(row.get("to"))
                block = row.get("block_number") or row.get("blockNumber")
                timestamp = row.get("timestamp")
                method = row.get("method")
                tx_hash = row.get("hash") or row.get("transaction_hash")
                index = row.get("index")
            else:
                sender = _party(getattr(row, "from_address", ""))
                recipient = _party(getattr(row, "to", ""))
                block = getattr(row, "block_number", None)
                timestamp = getattr(row, "block_timestamp", None)
                method = getattr(row, "method", None)
                tx_hash = getattr(row, "hash", "")
                index = getattr(row, "transaction_index", None)
            value = _value(row)
            if (
                not value
                or not recipient
                or recipient in excluded
                or sender == recipient
            ):
                continue
            if is_contract and is_contract(recipient):
                continue
            key = (str(tx_hash), sender, recipient, value, str(index))
            unique.setdefault(
                key,
                dict(
                    tx=tx_hash,
                    block=block,
                    index=index,
                    timestamp=timestamp,
                    source=sender,
                    destination=recipient,
                    value_raw=str(value),
                    value=value / 10**18,
                    method=method,
                    kind="internal"
                    if isinstance(row, dict) and row.get("index") is not None
                    else "transaction",
                    wallet=wallet,
                ),
            )
    return sorted(
        unique.values(),
        key=lambda edge: (
            edge["timestamp"] or 0,
            str(edge["tx"]),
            edge["index"] or 0,
            edge["source"],
            edge["destination"],
        ),
    )


def counterparties(
    edges: Iterable[dict[str, Any]], core: Iterable[str]
) -> dict[str, Any]:
    core = {addr(item) for item in core}
    funders: Counter[str] = Counter()
    collectors: Counter[str] = Counter()
    inbound = defaultdict(int)
    outbound = defaultdict(int)
    for edge in edges:
        source, destination = edge["source"], edge["destination"]
        if source not in core and destination in core:
            funders[source] += edge["value"]
            inbound[destination] += edge["value"]
        elif source in core and destination not in core:
            collectors[destination] += edge["value"]
            outbound[source] += edge["value"]
    return {
        "funders": dict(funders.most_common()),
        "collectors": dict(collectors.most_common()),
        "inbound": dict(inbound),
        "outbound": dict(outbound),
    }


def _eth(value: int | None) -> float | None:
    return from_wei(value) if value is not None else None


def analyze_funding(
    store: ArtifactStore,
    profile: Launch,
    *,
    fresh_nonce: int = 10,
    hub_min: int = 3,
    output: str = "analysis/funding",
) -> dict[str, Any]:
    """Build deduplicated native edges, wallet flows, hubs, and fresh-wallet rows."""
    if fresh_nonce < 0:
        raise ValueError("Fresh-wallet nonce must be non-negative")
    if hub_min < 2:
        raise ValueError("Fan-out hub minimum must be at least two")
    relative_root = "evidence/funding/wallets"
    directories = store.directories(relative_root)
    if not directories:
        raise InvariantError("No funding evidence; run collect funding first")

    per_wallet: dict[str, dict[str, Any]] = {}
    for directory_name in directories:
        wallet = addr(directory_name)
        if wallet != directory_name:
            raise InvariantError(f"Invalid funding wallet directory: {directory_name}")
        relative = f"evidence/funding/wallets/{wallet}"
        transactions = store.read_json(f"{relative}/transactions.json")
        internals = store.read_json(f"{relative}/internal_transfers.json")
        meta = store.read_json(f"{relative}/meta.json")
        if transactions is None or internals is None or meta is None:
            raise InvariantError(f"Incomplete funding evidence for {wallet}")
        if not isinstance(transactions, list) or not isinstance(internals, list):
            raise InvariantError(f"Malformed funding evidence for {wallet}")
        per_wallet[wallet] = {
            "transactions": transactions,
            "internal": internals,
            "meta": meta,
        }

    wallets = tuple(sorted(per_wallet))
    by_hash: dict[str, Any] = {}
    for data in per_wallet.values():
        for row in data["transactions"]:
            tx_hash = _row_hash(row)
            if not tx_hash:
                raise InvariantError("Funding transaction has no hash")
            by_hash.setdefault(tx_hash, row)
    transactions = sorted(
        by_hash.values(),
        key=lambda row: (
            _row_int(row, "block_number"),
            _row_int(row, "position", "transaction_index"),
            _row_hash(row),
        ),
    )
    internals = dedupe_internal_transfers(
        row for data in per_wallet.values() for row in data["internal"]
    )
    internals.sort(
        key=lambda row: (
            _row_int(row, "block_number"),
            _row_hash(row),
            _row_int(row, "index"),
        )
    )

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
    histories = {
        wallet: data["transactions"] + data["internal"]
        for wallet, data in per_wallet.items()
    }
    edges = native_edges(histories, exclude=protocol)
    core = set(wallets)
    balances = {
        wallet: _row_int(data["meta"], "balance_raw")
        for wallet, data in per_wallet.items()
    }
    flow = flow_statement(
        transactions,
        internals,
        members=wallets,
        balances=balances,
    )
    flow_rows = {row["address"]: row for row in flow["rows"]}

    funders_raw: dict[str, int] = defaultdict(int)
    funder_edges: Counter[str] = Counter()
    collectors_raw: dict[str, int] = defaultdict(int)
    collector_edges: Counter[str] = Counter()
    for edge in edges:
        value = int(edge["value_raw"])
        source, destination = edge["source"], edge["destination"]
        if source in protocol:
            continue
        if source not in core and destination in core:
            funders_raw[source] += value
            funder_edges[source] += 1
        elif source in core and destination not in core:
            collectors_raw[destination] += value
            collector_edges[destination] += 1

    wallet_rows = []
    # Index external inbound edges once instead of scanning every edge per wallet.
    external_inbound: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source, destination = edge["source"], edge["destination"]
        if destination in core and source not in core and source not in protocol:
            external_inbound[destination].append(edge)
    for wallet in wallets:
        data = per_wallet[wallet]
        meta = data["meta"]
        flow_row = flow_rows[wallet]
        inbound = flow_row["inflow"]
        outbound = flow_row["outflow"]
        gas = flow_row["gas"]
        net = flow_row["flow"]
        if inbound - outbound - gas != net:
            raise InvariantError(
                f"Funding flow does not reconcile for {wallet}: "
                f"{inbound} - {outbound} - {gas} != {net}"
            )
        balance = _row_int(meta, "balance_raw")
        if flow_row["balance"] != balance:
            raise InvariantError(f"Funding balance does not match meta for {wallet}")
        blocks = [
            _row_int(row, "block_number")
            for row in data["transactions"] + data["internal"]
            if _row_int(row, "block_number")
        ]
        external_in = external_inbound.get(wallet, ())
        top = max(external_in, key=lambda edge: int(edge["value_raw"]), default=None)
        top_value = int(top["value_raw"]) if top is not None else 0
        wallet_rows.append(
            {
                "wallet": wallet,
                "nonce": _row_int(meta, "nonce"),
                "balance_raw": balance,
                "balance_eth": _eth(balance),
                "is_contract": bool(meta.get("is_contract")),
                "transactions": len(data["transactions"]),
                "internal_transfers": len(dedupe_internal_transfers(data["internal"])),
                "inbound_raw": inbound,
                "inbound_eth": _eth(inbound),
                "outbound_raw": outbound,
                "outbound_eth": _eth(outbound),
                "gas_raw": gas,
                "gas_eth": _eth(gas),
                "net_raw": net,
                "net_eth": _eth(net),
                "first_block": min(blocks) if blocks else None,
                "last_block": max(blocks) if blocks else None,
                "fresh": _row_int(meta, "nonce") <= fresh_nonce,
                "top_funder": top["source"] if top is not None else "",
                "top_funder_raw": top_value,
                "top_funder_eth": _eth(top_value),
            }
        )

    hubs: dict[str, dict[str, Any]] = {}
    for edge in edges:
        source = edge["source"]
        if source in protocol:
            continue
        data = hubs.setdefault(
            source,
            {
                "recipients": set(),
                "value_raw": 0,
                "edges": 0,
                "methods": Counter(),
            },
        )
        data["recipients"].add(edge["destination"])
        data["value_raw"] += int(edge["value_raw"])
        data["edges"] += 1
        data["methods"][edge["method"] or edge["kind"]] += 1
    hub_rows = [
        {
            "source": source,
            "source_in_core": source in core,
            "recipients": len(data["recipients"]),
            "value_raw": data["value_raw"],
            "value_eth": _eth(data["value_raw"]),
            "edges": data["edges"],
            "methods": dict(
                sorted(data["methods"].items(), key=lambda item: (-item[1], item[0]))
            ),
        }
        for source, data in hubs.items()
        if len(data["recipients"]) >= hub_min
    ]
    hub_rows.sort(
        key=lambda row: (-row["recipients"], -row["value_raw"], row["source"])
    )
    fresh_rows = sorted(
        (row for row in wallet_rows if row["fresh"]),
        key=lambda row: (row["nonce"], row["wallet"]),
    )
    methods = Counter(edge["method"] or edge["kind"] for edge in edges)
    totals = flow["totals"]
    start_blocks = {data["meta"].get("start_block") for data in per_wallet.values()}
    summary = {
        "profile": profile.name,
        "wallets": len(wallets),
        "transactions": len(transactions),
        "internal_transfers": len(internals),
        "edges": len(edges),
        "start_block": next(iter(start_blocks)) if len(start_blocks) == 1 else None,
        "fresh_nonce": fresh_nonce,
        "hub_min": hub_min,
        "flow": {
            "inflow_raw": totals["inflow"],
            "inflow_eth": _eth(totals["inflow"]),
            "outflow_raw": totals["outflow"],
            "outflow_eth": _eth(totals["outflow"]),
            "gas_raw": totals["gas"],
            "gas_eth": _eth(totals["gas"]),
            "internal_raw": totals["internal"],
            "internal_eth": _eth(totals["internal"]),
            "net_flow_raw": totals["net_flow"],
            "net_flow_eth": _eth(totals["net_flow"]),
            "balance_now_raw": totals.get("balance_now"),
            "balance_now_eth": _eth(totals.get("balance_now")),
            "residual_raw": totals.get("residual"),
            "residual_eth": _eth(totals.get("residual")),
            "reconciled": totals.get("residual") == 0,
        },
        "counterparties": {
            "funders": [
                {
                    "address": address,
                    "value_raw": value,
                    "value_eth": _eth(value),
                    "edges": funder_edges[address],
                }
                for address, value in sorted(
                    funders_raw.items(), key=lambda item: (-item[1], item[0])
                )[:10]
            ],
            "collectors": [
                {
                    "address": address,
                    "value_raw": value,
                    "value_eth": _eth(value),
                    "edges": collector_edges[address],
                }
                for address, value in sorted(
                    collectors_raw.items(), key=lambda item: (-item[1], item[0])
                )[:10]
            ],
        },
        "fanout_hubs": hub_rows[:10],
        "fresh_wallets": fresh_rows[:10],
        "methods": dict(sorted(methods.items(), key=lambda item: (-item[1], item[0]))),
        "top_inflow_wallets": sorted(
            wallet_rows, key=lambda row: (-row["inbound_raw"], row["wallet"])
        )[:10],
    }

    store.write_csv(
        f"{output}/edges.csv",
        [
            {
                "tx": edge["tx"],
                "block": edge["block"],
                "timestamp": edge["timestamp"],
                "source": edge["source"],
                "destination": edge["destination"],
                "value_raw": edge["value_raw"],
                "value_eth": edge["value"],
                "method": edge["method"] or "",
                "kind": edge["kind"],
                "wallet": edge["wallet"],
            }
            for edge in edges
        ],
        fields=(
            "tx",
            "block",
            "timestamp",
            "source",
            "destination",
            "value_raw",
            "value_eth",
            "method",
            "kind",
            "wallet",
        ),
    )
    store.write_csv(
        f"{output}/wallets.csv",
        wallet_rows,
        fields=(
            "wallet",
            "nonce",
            "balance_raw",
            "balance_eth",
            "is_contract",
            "transactions",
            "internal_transfers",
            "inbound_raw",
            "inbound_eth",
            "outbound_raw",
            "outbound_eth",
            "gas_raw",
            "gas_eth",
            "net_raw",
            "net_eth",
            "first_block",
            "last_block",
            "fresh",
            "top_funder",
            "top_funder_raw",
            "top_funder_eth",
        ),
    )
    counterparty_rows = [
        {
            "role": "funder",
            "address": address,
            "value_raw": value,
            "value_eth": _eth(value),
            "edges": funder_edges[address],
        }
        for address, value in sorted(
            funders_raw.items(), key=lambda item: (-item[1], item[0])
        )
    ] + [
        {
            "role": "collector",
            "address": address,
            "value_raw": value,
            "value_eth": _eth(value),
            "edges": collector_edges[address],
        }
        for address, value in sorted(
            collectors_raw.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    store.write_csv(
        f"{output}/counterparties.csv",
        counterparty_rows,
        fields=("role", "address", "value_raw", "value_eth", "edges"),
    )
    store.write_json(f"{output}/summary.json", summary)
    return summary
