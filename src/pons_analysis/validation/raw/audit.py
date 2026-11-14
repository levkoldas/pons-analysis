"""Read-only validation of raw workspace evidence before analysis.

Checks are explicit rows with a path, a boolean, and a detail. Validation reads
only ``evidence/`` documents; it never rewrites them. Results are written to
``analysis/validation.json`` and returned to the CLI/API.
"""

from typing import Any

from pons_analysis.core.evm import addr
from pons_analysis.core.models import (
    Coverage,
    Launch,
    LaunchRecord,
    RpcLog,
    RpcReceipt,
)
from pons_analysis.core.validation import reconcile_events, transfer_ledger
from pons_analysis.storage.store import ArtifactStore


def _row(name: str, ok: bool, detail: str, path: str | None = None) -> dict[str, Any]:
    return {
        "check": name,
        "ok": ok,
        "detail": detail,
        "path": path or "",
    }


def _load_json(store: ArtifactStore, relative: str, model=None):
    try:
        value = store.read_json(relative, model=model)
    except Exception as exc:
        return None, f"invalid {relative}: {type(exc).__name__}: {exc}"
    if value is None:
        return None, f"missing {relative}"
    return value, None


def _load_list(
    store: ArtifactStore, relative: str, model
) -> tuple[list[Any] | None, str | None]:
    payload, error = _load_json(store, relative)
    if error:
        return None, error
    try:
        return [model.model_validate(item) for item in payload], None
    except Exception as exc:
        return None, f"invalid {relative}: {type(exc).__name__}: {exc}"


def _block_timestamps(payload: Any) -> tuple[dict[int, int], str | None]:
    if not isinstance(payload, dict):
        return {}, "blocks document must be an object"
    timestamps = {}
    for key, block in payload.items():
        try:
            value = block["timestamp"]
            timestamps[int(key)] = (
                int(value, 16) if isinstance(value, str) else int(value)
            )
        except (KeyError, TypeError, ValueError) as exc:
            return {}, f"invalid block {key}: {exc}"
    return timestamps, None


def _int_field(value: Any) -> int | None:
    try:
        return (
            int(value, 16)
            if isinstance(value, str) and value.startswith("0x")
            else int(value)
        )
    except (TypeError, ValueError):
        return None


def _validate_launch(
    store: ArtifactStore, profile: Launch, checks: list[dict[str, Any]]
) -> dict[int, int]:
    path = "evidence/launch"
    if not store.is_dir(path):
        return {}
    coverage, error = _load_json(store, f"{path}/coverage.json", Coverage)
    checks.append(
        _row(
            "launch.coverage",
            coverage is not None,
            error or "coverage parsed",
            f"{path}/coverage.json",
        )
    )
    record, error = _load_json(store, f"{path}/record.json", LaunchRecord)
    checks.append(
        _row(
            "launch.record",
            record is not None,
            error or "launch record parsed",
            f"{path}/record.json",
        )
    )
    blocks_payload, error = _load_json(store, f"{path}/blocks.json")
    timestamps, block_error = _block_timestamps(blocks_payload)
    checks.append(
        _row(
            "launch.blocks",
            bool(timestamps) and not block_error,
            block_error or "block timestamps parsed",
            f"{path}/blocks.json",
        )
    )
    transfers, transfers_error = _load_list(store, f"{path}/transfers.json", RpcLog)
    curve_logs, curve_error = _load_list(store, f"{path}/curve_logs.json", RpcLog)
    swaps, swaps_error = _load_list(store, f"{path}/swaps.json", RpcLog)
    receipts, receipts_error = _load_list(store, f"{path}/receipts.json", RpcReceipt)
    for name, rows, error, path_name in (
        ("launch.transfers", transfers, transfers_error, "transfers.json"),
        ("launch.curve_logs", curve_logs, curve_error, "curve_logs.json"),
        ("launch.swaps", swaps, swaps_error, "swaps.json"),
        ("launch.receipts", receipts, receipts_error, "receipts.json"),
    ):
        checks.append(
            _row(
                name,
                rows is not None,
                error or f"{len(rows)} rows",
                f"{path}/{path_name}",
            )
        )

    if coverage is not None:
        expected_start = (
            profile.launch_start_block
            if profile.launch_start_block is not None
            else profile.start_block
        )
        expected_end = (
            profile.migration.block if profile.migration is not None else coverage.head
        )
        checks.append(
            _row(
                "launch.coverage.profile",
                coverage.start_block == expected_start
                and coverage.end_block == expected_end,
                (
                    f"start={coverage.start_block} expected={expected_start}; "
                    f"end={coverage.end_block} expected={expected_end}"
                ),
                f"{path}/coverage.json",
            )
        )
        checks.append(
            _row(
                "launch.coverage.bounds",
                coverage.start_block <= coverage.end_block
                and coverage.head >= coverage.end_block,
                f"start={coverage.start_block} end={coverage.end_block} head={coverage.head}",
                f"{path}/coverage.json",
            )
        )
        present = {
            "start": coverage.start_block in timestamps,
            "end": coverage.end_block in timestamps,
            "head": coverage.head in timestamps,
        }
        checks.append(
            _row(
                "launch.coverage.blocks",
                all(present.values()),
                ", ".join(name for name, ok in present.items() if not ok)
                or "start, end, and head blocks present",
                f"{path}/blocks.json",
            )
        )
        if present["start"]:
            checks.append(
                _row(
                    "launch.coverage.start_timestamp",
                    coverage.start_timestamp == timestamps[coverage.start_block],
                    f"{coverage.start_timestamp} vs {timestamps[coverage.start_block]}",
                    f"{path}/coverage.json",
                )
            )
        if present["end"]:
            checks.append(
                _row(
                    "launch.coverage.end_timestamp",
                    coverage.end_block_timestamp == timestamps[coverage.end_block]
                    and coverage.end_timestamp_exclusive
                    == timestamps[coverage.end_block] + 1,
                    (
                        f"end={coverage.end_block_timestamp} "
                        f"exclusive={coverage.end_timestamp_exclusive} "
                        f"block={timestamps[coverage.end_block]}"
                    ),
                    f"{path}/coverage.json",
                )
            )
            next_timestamp = timestamps.get(coverage.end_block + 1)
            next_required = coverage.head > coverage.end_block
            checks.append(
                _row(
                    "launch.coverage.next_timestamp",
                    (
                        next_timestamp is not None
                        and coverage.next_block_timestamp == next_timestamp
                    )
                    if next_required
                    else (
                        next_timestamp is None
                        or coverage.next_block_timestamp == next_timestamp
                    ),
                    (
                        f"{coverage.next_block_timestamp} vs {next_timestamp}"
                        if next_timestamp is not None
                        else f"block {coverage.end_block + 1} not covered by head {coverage.head}"
                    ),
                    f"{path}/blocks.json",
                )
            )
    if record is not None:
        checks.append(
            _row(
                "launch.record.token",
                record.token == profile.token,
                f"{record.token} vs {profile.token}",
                f"{path}/record.json",
            )
        )
        checks.append(
            _row(
                "launch.record.curve",
                profile.curve is None or record.curve == profile.curve,
                f"{record.curve} vs {profile.curve}",
                f"{path}/record.json",
            )
        )
    if transfers is not None:
        bad = [
            log.transaction_hash
            for log in transfers
            if log.address != profile.token
            or not log.topics
            or log.topics[0] != profile.transfer_topic
        ]
        checks.append(
            _row(
                "launch.transfer_contract",
                not bad,
                f"{len(bad)} unexpected logs",
                f"{path}/transfers.json",
            )
        )
        try:
            balance = transfer_ledger(transfers)
            checks.append(
                _row(
                    "launch.transfer_ledger",
                    True,
                    f"{len(balance)} balances conserve",
                    f"{path}/transfers.json",
                )
            )
        except Exception as exc:
            checks.append(
                _row(
                    "launch.transfer_ledger",
                    False,
                    f"{type(exc).__name__}: {exc}",
                    f"{path}/transfers.json",
                )
            )
    if curve_logs is not None:
        bad = (
            [log.transaction_hash for log in curve_logs if log.address != profile.curve]
            if profile.curve is not None
            else []
        )
        checks.append(
            _row(
                "launch.curve_contract",
                not bad,
                f"{len(bad)} unexpected logs",
                f"{path}/curve_logs.json",
            )
        )
    if swaps is not None:
        bad = [
            log.transaction_hash
            for log in swaps
            if log.address != profile.manager
            or log.topics[:2] != [profile.swap_topic, profile.pool_id]
        ]
        checks.append(
            _row(
                "launch.swap_pool",
                not bad,
                f"{len(bad)} unexpected logs",
                f"{path}/swaps.json",
            )
        )
    if all(value is not None for value in (transfers, curve_logs, swaps, receipts)):
        try:
            result = reconcile_events(transfers + curve_logs + swaps, receipts)
            checks.append(
                _row(
                    "launch.events",
                    True,
                    f"{result['events']} events in {result['transactions']} transactions",
                    f"{path}/receipts.json",
                )
            )
        except Exception as exc:
            checks.append(
                _row(
                    "launch.events",
                    False,
                    f"{type(exc).__name__}: {exc}",
                    f"{path}/receipts.json",
                )
            )
        if coverage is not None:
            checks.append(
                _row(
                    "launch.coverage.transactions",
                    coverage.transactions == len(receipts),
                    f"{coverage.transactions} vs {len(receipts)}",
                    f"{path}/coverage.json",
                )
            )
    return timestamps


def _validate_window(
    store: ArtifactStore,
    profile: Launch,
    checks: list[dict[str, Any]],
    launch_timestamps: dict[int, int],
) -> None:
    if not store.is_dir("evidence/windows"):
        return
    names = sorted(
        name for name in store.directories("evidence/windows") if name.isdigit()
    )
    if not names:
        checks.append(
            _row(
                "windows.present",
                False,
                "evidence/windows exists but has no numeric window directories",
                "evidence/windows",
            )
        )
        return
    for name in names:
        path = f"evidence/windows/{name}"
        bounds, bounds_error = _load_json(store, f"{path}/bounds.json")
        checks.append(
            _row(
                f"window.{name}.bounds",
                isinstance(bounds, dict),
                bounds_error or "bounds parsed",
                f"{path}/bounds.json",
            )
        )
        token_logs, token_error = _load_list(store, f"{path}/token_logs.json", RpcLog)
        swaps, swap_error = _load_list(store, f"{path}/swaps_logs.json", RpcLog)
        if profile.migration is None:
            curve_logs, curve_error = _load_list(
                store, f"{path}/curve_logs.json", RpcLog
            )
            checks.append(
                _row(
                    f"window.{name}.curve_logs",
                    curve_logs is not None,
                    curve_error or f"{len(curve_logs)} rows",
                    f"{path}/curve_logs.json",
                )
            )
            if curve_logs is not None:
                bad_curve = [
                    log.transaction_hash
                    for log in curve_logs
                    if profile.curve is not None and log.address != profile.curve
                ]
                checks.append(
                    _row(
                        f"window.{name}.curve_contract",
                        not bad_curve,
                        f"{len(bad_curve)} unexpected logs",
                        f"{path}/curve_logs.json",
                    )
                )
        receipts, receipt_error = _load_list(store, f"{path}/receipts.json", RpcReceipt)
        blocks_payload, blocks_error = _load_json(store, f"{path}/blocks.json")
        window_timestamps, block_error = _block_timestamps(blocks_payload)
        timestamps = dict(launch_timestamps)
        timestamps.update(window_timestamps)
        for label, rows, error, file_name in (
            ("token_logs", token_logs, token_error, "token_logs.json"),
            ("swaps", swaps, swap_error, "swaps_logs.json"),
            ("receipts", receipts, receipt_error, "receipts.json"),
        ):
            checks.append(
                _row(
                    f"window.{name}.{label}",
                    rows is not None,
                    error or f"{len(rows)} rows",
                    f"{path}/{file_name}",
                )
            )
        checks.append(
            _row(
                f"window.{name}.blocks",
                bool(window_timestamps) and not blocks_error and not block_error,
                block_error or "block timestamps parsed",
                f"{path}/blocks.json",
            )
        )
        if not isinstance(bounds, dict):
            continue
        required = {
            "start_timestamp",
            "end_timestamp_exclusive",
            "start_block",
            "end_block",
            "end_block_timestamp",
            "next_block_timestamp",
        }
        missing = sorted(required - bounds.keys())
        checks.append(
            _row(
                f"window.{name}.bounds.keys",
                not missing,
                ", ".join(missing) or "all bounds present",
                f"{path}/bounds.json",
            )
        )
        checks.append(
            _row(
                f"window.{name}.profile",
                _int_field(bounds.get("start_block")) == profile.start_block
                and _int_field(bounds.get("start_timestamp"))
                == profile.start_timestamp,
                (
                    f"start_block={bounds.get('start_block')} "
                    f"expected={profile.start_block}; "
                    f"start_timestamp={bounds.get('start_timestamp')} "
                    f"expected={profile.start_timestamp}"
                ),
                f"{path}/bounds.json",
            )
        )
        start_block = _int_field(bounds.get("start_block"))
        end_block = _int_field(bounds.get("end_block"))
        start_timestamp = _int_field(bounds.get("start_timestamp"))
        end_timestamp = _int_field(bounds.get("end_timestamp_exclusive"))
        end_block_timestamp = _int_field(bounds.get("end_block_timestamp"))
        next_timestamp = _int_field(bounds.get("next_block_timestamp"))
        expected_end = profile.start_timestamp + int(name) * 60
        checks.append(
            _row(
                f"window.{name}.duration",
                end_timestamp == expected_end,
                f"{end_timestamp} vs {expected_end}",
                f"{path}/bounds.json",
            )
        )
        if start_block is not None and start_timestamp is not None:
            checks.append(
                _row(
                    f"window.{name}.start_timestamp",
                    start_block in timestamps
                    and timestamps[start_block] == start_timestamp,
                    (
                        f"{start_timestamp} vs {timestamps.get(start_block)}"
                        if start_block in timestamps
                        else f"block {start_block} timestamp missing"
                    ),
                    f"{path}/bounds.json",
                )
            )
        if end_block is not None and end_block_timestamp is not None:
            checks.append(
                _row(
                    f"window.{name}.end_timestamp",
                    end_block in timestamps
                    and end_block_timestamp == timestamps[end_block],
                    (
                        f"{end_block_timestamp} vs {timestamps.get(end_block)}"
                        if end_block in timestamps
                        else f"block {end_block} timestamp missing"
                    ),
                    f"{path}/bounds.json",
                )
            )
            checks.append(
                _row(
                    f"window.{name}.next_timestamp",
                    (
                        next_timestamp is not None
                        and end_block + 1 in timestamps
                        and next_timestamp == timestamps[end_block + 1]
                    )
                    or (
                        next_timestamp is None
                        and end_block + 1 > (_int_field(bounds.get("head")) or 0)
                    ),
                    (
                        f"{next_timestamp} vs {timestamps.get(end_block + 1)}"
                        if end_block + 1 in timestamps
                        else f"block {end_block + 1} timestamp missing"
                    ),
                    f"{path}/bounds.json",
                )
            )
        if all(
            value is not None
            for value in (
                end_block_timestamp,
                end_timestamp,
                next_timestamp,
            )
        ):
            checks.append(
                _row(
                    f"window.{name}.timestamp_span",
                    end_block_timestamp < end_timestamp <= next_timestamp,
                    f"{end_block_timestamp} < {end_timestamp} <= {next_timestamp}",
                    f"{path}/bounds.json",
                )
            )
        if token_logs is not None:
            bad = [
                log.transaction_hash
                for log in token_logs
                if log.address != profile.token
                or not log.topics
                or log.topics[0] != profile.transfer_topic
            ]
            checks.append(
                _row(
                    f"window.{name}.transfer_contract",
                    not bad,
                    f"{len(bad)} unexpected logs",
                    f"{path}/token_logs.json",
                )
            )
        if swaps is not None:
            bad = [
                log.transaction_hash
                for log in swaps
                if log.address != profile.manager
                or log.topics[:2] != [profile.swap_topic, profile.pool_id]
            ]
            checks.append(
                _row(
                    f"window.{name}.swap_pool",
                    not bad,
                    f"{len(bad)} unexpected logs",
                    f"{path}/swaps_logs.json",
                )
            )
        logs = (token_logs or []) + (swaps or [])
        if logs:
            keys = {(log.transaction_hash, log.log_index) for log in logs}
            checks.append(
                _row(
                    f"window.{name}.unique_events",
                    len(keys) == len(logs),
                    f"{len(logs) - len(keys)} duplicates",
                    f"{path}/",
                )
            )
        if token_logs is not None and swaps is not None and receipts is not None:
            try:
                result = reconcile_events(token_logs + swaps, receipts)
                checks.append(
                    _row(
                        f"window.{name}.events",
                        True,
                        f"{result['events']} events in {result['transactions']} transactions",
                        f"{path}/receipts.json",
                    )
                )
            except Exception as exc:
                checks.append(
                    _row(
                        f"window.{name}.events",
                        False,
                        f"{type(exc).__name__}: {exc}",
                        f"{path}/receipts.json",
                    )
                )
        if (
            logs
            and receipts is not None
            and all(value is not None for value in (start_timestamp, end_timestamp))
        ):
            bad_times = []
            for log in logs:
                timestamp = timestamps.get(log.block_number)
                if timestamp is None or not (
                    start_timestamp <= timestamp < end_timestamp
                ):
                    bad_times.append(log.transaction_hash)
            checks.append(
                _row(
                    f"window.{name}.event_timestamps",
                    not bad_times,
                    f"{len(bad_times)} events outside the window",
                    f"{path}/",
                )
            )
            bad_receipts = []
            for receipt in receipts:
                timestamp = receipt.block_timestamp
                if timestamp is None:
                    timestamp = timestamps.get(receipt.block_number)
                if timestamp is None or not (
                    start_timestamp <= timestamp < end_timestamp
                ):
                    bad_receipts.append(receipt.transaction_hash)
            checks.append(
                _row(
                    f"window.{name}.receipt_timestamps",
                    not bad_receipts,
                    f"{len(bad_receipts)} receipts outside the window",
                    f"{path}/receipts.json",
                )
            )


def _validate_funding(store: ArtifactStore, checks: list[dict[str, Any]]) -> None:
    if not store.is_dir("evidence/funding/wallets"):
        return
    names = store.directories("evidence/funding/wallets")
    if not names:
        checks.append(
            _row(
                "funding.wallets",
                False,
                "evidence/funding/wallets exists but is empty",
                "evidence/funding/wallets",
            )
        )
        return
    for wallet in names:
        try:
            normalized = addr(wallet)
        except ValueError:
            normalized = None
        if normalized != wallet:
            checks.append(
                _row(
                    f"funding.{wallet}.name",
                    False,
                    "wallet directory is not a normalized address",
                    f"evidence/funding/wallets/{wallet}",
                )
            )
            continue
        base = f"evidence/funding/wallets/{wallet}"
        meta, meta_error = _load_json(store, f"{base}/meta.json")
        transactions, tx_error = _load_json(store, f"{base}/transactions.json")
        internals, internal_error = _load_json(store, f"{base}/internal_transfers.json")
        checks.append(
            _row(
                f"funding.{wallet[:10]}.meta",
                isinstance(meta, dict),
                meta_error or "meta parsed",
                f"{base}/meta.json",
            )
        )
        checks.append(
            _row(
                f"funding.{wallet[:10]}.transactions",
                isinstance(transactions, list),
                tx_error or f"{len(transactions or [])} rows",
                f"{base}/transactions.json",
            )
        )
        checks.append(
            _row(
                f"funding.{wallet[:10]}.internal",
                isinstance(internals, list),
                internal_error or f"{len(internals or [])} rows",
                f"{base}/internal_transfers.json",
            )
        )
        if isinstance(meta, dict):
            checks.append(
                _row(
                    f"funding.{wallet[:10]}.wallet",
                    meta.get("wallet") == wallet,
                    f"{meta.get('wallet')} vs {wallet}",
                    f"{base}/meta.json",
                )
            )
            checks.append(
                _row(
                    f"funding.{wallet[:10]}.state",
                    _int_field(meta.get("nonce")) is not None
                    and _int_field(meta.get("balance_raw")) is not None,
                    "nonce and balance_raw are integers",
                    f"{base}/meta.json",
                )
            )


def validate_workspace(
    store: ArtifactStore,
    profile: Launch,
    *,
    output: str = "analysis/validation.json",
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    launch_timestamps = _validate_launch(store, profile, checks)
    _validate_window(store, profile, checks, launch_timestamps)
    _validate_funding(store, checks)

    has_evidence = any(
        store.is_dir(path)
        for path in (
            "evidence/launch",
            "evidence/windows",
            "evidence/funding",
        )
    )
    if not has_evidence:
        checks.append(
            _row(
                "workspace.evidence",
                False,
                "no launch, window, or funding evidence found",
                "evidence/",
            )
        )
    failures = sum(not check["ok"] for check in checks)
    report = {
        "profile": profile.name,
        "passed": failures == 0,
        "failures": failures,
        "checks": checks,
    }
    store.write_json(output, report)
    return report
