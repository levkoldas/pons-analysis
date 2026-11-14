"""Launch accounting for curve and v4 phases, driven only by a profile."""

import collections
import datetime
import statistics
from itertools import groupby, pairwise
from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import addr, from_wei, sig, signed, words
from pons_analysis.core.models import (
    Coverage,
    Launch,
    LaunchRecord,
    RpcBlock,
    RpcLog,
    RpcReceipt,
    RpcTransaction,
)
from pons_analysis.core.validation import reconcile_events, transfer_ledger
from pons_analysis.storage.store import ArtifactStore

ZERO = "0x" + "0" * 40


def _utc(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.UTC).isoformat()


def _load_list(store: ArtifactStore, name: str, model) -> list[Any]:
    payload = store.read_json(f"evidence/launch/{name}.json")
    if payload is None:
        raise InvariantError(f"Missing launch artifact: {name}.json")
    return [model.model_validate(item) for item in payload]


def _load_map(store: ArtifactStore, name: str, model) -> dict[str, Any]:
    payload = store.read_json(f"evidence/launch/{name}.json")
    if payload is None:
        raise InvariantError(f"Missing launch artifact: {name}.json")
    return {key: model.model_validate(value) for key, value in payload.items()}


def analyze_launch(
    store: ArtifactStore, profile: Launch, *, output: str = "analysis/launch"
) -> dict[str, Any]:
    coverage = store.read_json("evidence/launch/coverage.json", model=Coverage)
    record = store.read_json("evidence/launch/record.json", model=LaunchRecord)
    if coverage is None or record is None:
        raise InvariantError("Launch evidence is incomplete: coverage/record missing")
    txs = _load_map(store, "txs", RpcTransaction)
    blocks = _load_map(store, "blocks", RpcBlock)
    receipts = _load_list(store, "receipts", RpcReceipt)
    transfers = _load_list(store, "transfers", RpcLog)
    curve_logs = _load_list(store, "curve_logs", RpcLog)
    swaps = _load_list(store, "swaps", RpcLog)

    reconcile_events(transfers + curve_logs + swaps, receipts)
    transfer_ledger(transfers)
    start = blocks[str(coverage.start_block)].timestamp
    protocol = {ZERO, profile.manager, profile.hook, record.curve}
    balances: collections.Counter[str] = collections.Counter()
    net: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    transfer_rows = []
    for log in transfers:
        sender, recipient = addr(log.topics[1]), addr(log.topics[2])
        value = int(log.data, 16)
        timestamp = blocks[str(log.block_number)].timestamp
        balances[sender] -= value
        balances[recipient] += value
        net[log.transaction_hash][sender] -= value
        net[log.transaction_hash][recipient] += value
        transfer_rows.append(
            dict(
                block=log.block_number,
                ts=timestamp,
                utc=_utc(timestamp),
                tx=log.transaction_hash,
                log_index=log.log_index,
                sender=sender,
                recipient=recipient,
                tokens_raw=str(value),
                tokens=value / 10**profile.decimals,
            )
        )

    curve_buy = sig("CurveBuy(address,address,uint256,uint256,uint256,uint256)")
    curve_sell = sig("CurveSell(address,address,uint256,uint256,uint256,uint256)")
    snipe_topic = sig("SnipeTaxCharged(address,uint256)")
    snipe_by_tx: collections.Counter[str] = collections.Counter()
    for log in curve_logs:
        if log.topics[0] == snipe_topic:
            snipe_by_tx[log.transaction_hash] += int(log.data, 16)

    trades = []
    for phase, logs in (("curve", curve_logs), ("v4", swaps)):
        for log in logs:
            if phase == "curve" and log.topics[0] not in (curve_buy, curve_sell):
                continue
            tx = txs[log.transaction_hash]
            timestamp = blocks[str(log.block_number)].timestamp
            values = words(log)
            if phase == "curve":
                side = "buy" if log.topics[0] == curve_buy else "sell"
                quote = values[0 if side == "buy" else 1]
                tokens = values[1 if side == "buy" else 0]
                wallet = addr(log.topics[2])
                caller = addr(log.topics[1])
                fee = values[2]
                tax = values[3]
                if (
                    wallet in protocol
                    or (side == "buy" and net[log.transaction_hash][wallet] <= 0)
                    or (side == "sell" and net[log.transaction_hash][wallet] >= 0)
                ):
                    candidates = {
                        account: amount
                        for account, amount in net[log.transaction_hash].items()
                        if account not in protocol
                        and (amount > 0 if side == "buy" else amount < 0)
                    }
                    if candidates:
                        wallet = max(
                            candidates, key=lambda account: abs(candidates[account])
                        )
            else:
                amount0, amount1 = signed(values[0]), signed(values[1])
                side = "buy" if amount0 < 0 else "sell"
                quote = abs(amount0)
                tokens = abs(amount1)
                caller = addr(log.topics[2])
                fee = tax = 0
                candidates = {
                    account: amount
                    for account, amount in net[log.transaction_hash].items()
                    if account not in protocol
                    and (amount > 0 if side == "buy" else amount < 0)
                }
                wallet = (
                    max(candidates, key=lambda account: abs(candidates[account]))
                    if candidates
                    else tx.from_address
                )
            trades.append(
                dict(
                    phase=phase,
                    block=log.block_number,
                    ts=timestamp,
                    utc=_utc(timestamp),
                    seconds_after_launch=timestamp - start,
                    tx=log.transaction_hash,
                    tx_index=tx.transaction_index,
                    log_index=log.log_index,
                    side=side,
                    wallet=wallet,
                    tx_from=tx.from_address,
                    tx_to=tx.to,
                    selector=tx.input[:10],
                    event_caller=caller,
                    quote_raw=str(quote),
                    tokens_raw=str(tokens),
                    quote_eth=from_wei(quote),
                    tokens=tokens / 10**profile.decimals,
                    fee_raw=str(fee),
                    creator_tax_raw=str(tax),
                    fee_eth=from_wei(fee),
                    creator_tax_eth=from_wei(tax),
                    snipe_tax_raw=str(snipe_by_tx[log.transaction_hash]),
                    snipe_tax_eth=from_wei(snipe_by_tx[log.transaction_hash]),
                    protocol_sweep=tx.from_address in profile.protocol_sweepers,
                )
            )
    if not trades:
        raise InvariantError("No curve or v4 trades decoded from launch evidence")
    trades.sort(key=lambda row: (row["block"], row["tx_index"] or 0, row["log_index"]))
    store.write_csv(f"{output}/trades.csv", trades)
    store.write_csv(f"{output}/transfers.csv", transfer_rows)

    curve_trades = [row for row in trades if row["phase"] == "curve"]
    v4_trades = [row for row in trades if row["phase"] == "v4"]
    migration_ts = (
        min(row["ts"] for row in v4_trades)
        if v4_trades
        else (curve_trades[-1]["ts"] if curve_trades else start)
    )
    duration_seconds = max(0, migration_ts - start)
    inter_trade = [b["ts"] - a["ts"] for a, b in pairwise(curve_trades)]
    per_second: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in trades:
        per_second[row["ts"]].append(row)
    peak_second_ts, peak_second_rows = (
        max(
            per_second.items(),
            key=lambda item: (
                len(item[1]),
                sum(row["quote_eth"] for row in item[1]),
                -item[0],
            ),
        )
        if per_second
        else (None, [])
    )
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    for row in trades:
        route = row["tx_to"] or "unknown"
        selector = row["selector"] or ""
        data = routes.setdefault(
            (route, selector),
            {
                "trades": 0,
                "buys": 0,
                "sells": 0,
                "wallets": set(),
                "volume_eth": 0.0,
                "first_utc": row["utc"],
                "last_utc": row["utc"],
            },
        )
        data["trades"] += 1
        data["buys"] += row["side"] == "buy"
        data["sells"] += row["side"] == "sell"
        data["wallets"].add(row["wallet"])
        data["volume_eth"] += row["quote_eth"]
        data["last_utc"] = row["utc"]
    route_rows = [
        {
            "route": route,
            "selector": selector,
            "trades": data["trades"],
            "buys": data["buys"],
            "sells": data["sells"],
            "wallets": len(data["wallets"]),
            "volume_eth": data["volume_eth"],
            "first_utc": data["first_utc"],
            "last_utc": data["last_utc"],
        }
        for (route, selector), data in routes.items()
    ]
    route_rows.sort(
        key=lambda row: (
            -row["trades"],
            -row["volume_eth"],
            row["route"],
            row["selector"],
        )
    )
    store.write_csv(
        f"{output}/routes.csv",
        route_rows,
        fields=(
            "route",
            "selector",
            "trades",
            "buys",
            "sells",
            "wallets",
            "volume_eth",
            "first_utc",
            "last_utc",
        ),
    )
    selector_rows: dict[str, dict[str, Any]] = {}
    for row in trades:
        selector = row["selector"] or ""
        data = selector_rows.setdefault(
            selector, {"trades": 0, "wallets": set(), "volume_eth": 0.0}
        )
        data["trades"] += 1
        data["wallets"].add(row["wallet"])
        data["volume_eth"] += row["quote_eth"]
    top_selectors = sorted(
        (
            {
                "selector": selector,
                "trades": data["trades"],
                "wallets": len(data["wallets"]),
                "volume_eth": data["volume_eth"],
            }
            for selector, data in selector_rows.items()
        ),
        key=lambda row: (-row["trades"], -row["volume_eth"], row["selector"]),
    )[:10]

    wallet_rows = []
    for wallet, group in groupby(
        sorted(trades, key=lambda row: row["wallet"]), key=lambda row: row["wallet"]
    ):
        rows = sorted(
            group,
            key=lambda row: (
                row["block"],
                row["tx_index"] or 0,
                row["log_index"],
            ),
        )
        buys = [row for row in rows if row["side"] == "buy"]
        sells = [row for row in rows if row["side"] == "sell"]
        intervals = [b["ts"] - a["ts"] for a, b in pairwise(rows)]
        switches = sum(a["side"] != b["side"] for a, b in pairwise(rows))
        buy_eth = sum(row["quote_eth"] for row in buys)
        sell_eth = sum(row["quote_eth"] for row in sells)
        wallet_rows.append(
            dict(
                wallet=wallet,
                trades=len(rows),
                buys=len(buys),
                sells=len(sells),
                buy_eth=buy_eth,
                sell_eth=sell_eth,
                volume_eth=buy_eth + sell_eth,
                event_net_eth=sell_eth - buy_eth,
                bought_tokens=sum(row["tokens"] for row in buys),
                sold_tokens=sum(row["tokens"] for row in sells),
                held_tokens=balances[wallet] / 10**profile.decimals,
                first_utc=rows[0]["utc"],
                last_utc=rows[-1]["utc"],
                active_seconds=rows[-1]["ts"] - rows[0]["ts"],
                median_interval_s=statistics.median(intervals) if intervals else None,
                interval_cv=(
                    statistics.pstdev(intervals) / statistics.mean(intervals)
                    if intervals and statistics.mean(intervals)
                    else None
                ),
                side_switch_rate=switches / (len(rows) - 1) if len(rows) > 1 else 0,
                senders=len({row["tx_from"] for row in rows}),
                routes=";".join(sorted({row["tx_to"] for row in rows if row["tx_to"]})),
                protocol_sweep=all(row["protocol_sweep"] for row in rows),
            )
        )
    wallet_rows.sort(key=lambda row: -row["trades"])
    store.write_csv(f"{output}/wallets.csv", wallet_rows)

    summaries = {}
    for name, rows in (
        ("all", trades),
        ("user", [row for row in trades if not row["protocol_sweep"]]),
        ("protocol", [row for row in trades if row["protocol_sweep"]]),
        ("curve", [row for row in trades if row["phase"] == "curve"]),
        ("v4", [row for row in trades if row["phase"] == "v4"]),
    ):
        summaries[name] = dict(
            trades=len(rows),
            buys=sum(row["side"] == "buy" for row in rows),
            sells=sum(row["side"] == "sell" for row in rows),
            wallets=len({row["wallet"] for row in rows}),
            senders=len({row["tx_from"] for row in rows}),
            volume_raw=str(sum(int(row["quote_raw"]) for row in rows)),
            volume_eth=sum(row["quote_eth"] for row in rows),
            buy_eth=sum(row["quote_eth"] for row in rows if row["side"] == "buy"),
            sell_eth=sum(row["quote_eth"] for row in rows if row["side"] == "sell"),
        )
    summaries.update(
        profile=profile.name,
        launch_utc=_utc(start),
        head_utc=_utc(blocks[str(coverage.head)].timestamp),
        head=coverage.head,
        migration=next((row["utc"] for row in trades if row["phase"] == "v4"), None),
        migration_seconds=(migration_ts - start if v4_trades else None),
        curve_duration_seconds=duration_seconds,
        trades_per_second=(
            len(curve_trades) / duration_seconds if duration_seconds else None
        ),
        wallets_per_second=(
            len({row["wallet"] for row in curve_trades}) / duration_seconds
            if duration_seconds
            else None
        ),
        median_intertrade_gap_s=(
            statistics.median(inter_trade) if inter_trade else None
        ),
        peak_second_utc=_utc(peak_second_ts) if peak_second_ts is not None else None,
        peak_second_trades=len(peak_second_rows),
        peak_second_volume_eth=sum(row["quote_eth"] for row in peak_second_rows),
        routes=len(route_rows),
        top_routes=route_rows[:10],
        top_selectors=top_selectors,
        supply_balance=sum(
            value for account, value in balances.items() if account != ZERO
        )
        / 10**profile.decimals,
        holders=sum(
            value > 0 for account, value in balances.items() if account != ZERO
        ),
    )
    store.write_json(f"{output}/summary.json", summaries)
    store.write_csv(
        f"{output}/holders.csv",
        [
            dict(
                wallet=account,
                tokens_raw=str(value),
                tokens=value / 10**profile.decimals,
                pct=value * 100 / profile.supply,
            )
            for account, value in sorted(balances.items(), key=lambda item: -item[1])
            if value > 0
        ],
    )
    return summaries
