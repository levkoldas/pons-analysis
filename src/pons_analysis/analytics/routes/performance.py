"""Wallet outcomes grouped by the launch route used for the first buy.

The route is the transaction target plus calldata selector observed in the
launch ledger. Wallets that never bought during launch (transfer recipients,
gas-only wallets) are reported separately rather than assigned a route.
"""

from typing import Any

from pons_analysis.core.errors import InvariantError
from pons_analysis.core.models import Launch
from pons_analysis.storage.store import ArtifactStore


def _float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _int(value: Any) -> int:
    return int(value) if value not in (None, "") else 0


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "") else None


def _short(wallet: str) -> str:
    return f"{wallet[:6]}…{wallet[-4:]}" if len(wallet) > 12 else wallet


ROUTE_FIELDS = (
    "route",
    "route_short",
    "selector",
    "wallets",
    "launch_trades",
    "launch_buys",
    "launch_sells",
    "launch_buy_volume_eth",
    "launch_sell_volume_eth",
    "net_quote_eth",
    "basis_deployed_eth",
    "realized_quote_eth",
    "unrealized_quote_eth",
    "gas_quote_eth",
    "net_roi_bps",
    "tokens_end",
    "profitable_wallets",
    "losing_wallets",
    "flat_wallets",
    "open_wallets",
    "retained_wallets",
    "retention_bps",
    "fee_wallets",
    "fee_volume_eth",
    "total_fee_eth",
    "fee_burden_bps",
)

WALLET_FIELDS = (
    "wallet",
    "route",
    "route_short",
    "selector",
    "tokens_end",
    "basis_deployed_eth",
    "realized_quote_eth",
    "unrealized_quote_eth",
    "gas_quote_eth",
    "net_quote_eth",
    "net_roi_bps",
    "open",
)


def analyze_route_performance(
    store: ArtifactStore,
    profile: Launch,
    *,
    minutes: int,
    output: str | None = None,
) -> dict[str, Any]:
    """Join first-launch-buy routes to exact position PnL."""
    if minutes < 1:
        raise ValueError("Window duration must be positive")
    trades_path = "analysis/launch/trades.csv"
    positions_path = f"analysis/positions-{minutes}/positions.csv"
    if not store.exists(trades_path):
        raise InvariantError("Missing launch trades; run analyze launch")
    if not store.exists(positions_path):
        raise InvariantError(
            f"Missing position evidence {positions_path}; run analyze positions {minutes}"
        )
    trades = store.read_csv(trades_path)
    positions = store.read_csv(positions_path)
    fee_path = f"analysis/fees-{minutes}/wallets.csv"
    fee_map = (
        {row["wallet"].lower(): row for row in store.read_csv(fee_path)}
        if store.exists(fee_path)
        else {}
    )
    if not trades:
        raise InvariantError("Launch trades are empty")
    if not positions:
        raise InvariantError("Position rows are empty")
    position_map = {row["wallet"].lower(): row for row in positions}
    routes: dict[tuple[str, str], dict[str, Any]] = {}
    first_buy: dict[str, tuple[str, str]] = {}
    for row in trades:
        route = row.get("tx_to", "").lower()
        selector = row.get("selector", "").lower()
        if not route:
            continue
        key = (route, selector)
        data = routes.setdefault(
            key,
            {
                "route": route,
                "route_short": _short(route),
                "selector": selector,
                "launch_trades": 0,
                "launch_buys": 0,
                "launch_sells": 0,
                "launch_buy_volume_eth": 0.0,
                "launch_sell_volume_eth": 0.0,
            },
        )
        data["launch_trades"] += 1
        side = row.get("side", "")
        value = _float(row.get("quote_eth")) or 0.0
        if side == "buy":
            data["launch_buys"] += 1
            data["launch_buy_volume_eth"] += value
        elif side == "sell":
            data["launch_sells"] += 1
            data["launch_sell_volume_eth"] += value
        wallet = row.get("wallet", "").lower()
        if side == "buy" and wallet and wallet not in first_buy:
            first_buy[wallet] = key
    wallet_rows = []
    route_wallets: dict[tuple[str, str], list[str]] = {}
    for wallet, key in first_buy.items():
        position = position_map.get(wallet)
        if position is None:
            continue
        net_raw = _optional_int(position.get("net_quote_raw"))
        basis_raw = _int(position.get("basis_deployed_raw"))
        net = net_raw / 10**18 if net_raw is not None else None
        basis = basis_raw / 10**18
        roi = _float(position.get("net_roi_bps"))
        route_wallets.setdefault(key, []).append(wallet)
        wallet_rows.append(
            {
                "wallet": wallet,
                "route": key[0],
                "route_short": _short(key[0]),
                "selector": key[1],
                "tokens_end": _float(position.get("tokens_end")),
                "basis_deployed_eth": basis,
                "realized_quote_eth": _int(position.get("realized_quote_raw")) / 10**18,
                "unrealized_quote_eth": (
                    _optional_int(position.get("unrealized_quote_raw")) / 10**18
                    if _optional_int(position.get("unrealized_quote_raw")) is not None
                    else None
                ),
                "gas_quote_eth": _int(position.get("gas_quote_raw")) / 10**18,
                "net_quote_eth": net,
                "net_roi_bps": roi,
                "open": str(position.get("open", "")).lower() == "true",
            }
        )
    rows = []
    for key, data in routes.items():
        assigned = route_wallets.get(key, [])
        selected = [position_map[wallet] for wallet in assigned]
        basis_raw = sum(_int(row.get("basis_deployed_raw")) for row in selected)
        net_values = [_optional_int(row.get("net_quote_raw")) for row in selected]
        net_known = all(value is not None for value in net_values)
        net_raw = (
            sum(value for value in net_values if value is not None)
            if net_known
            else None
        )
        realized_raw = sum(_int(row.get("realized_quote_raw")) for row in selected)
        sale_pnl_raw = sum(_int(row.get("sale_pnl_raw")) for row in selected)
        gas_raw = sum(_int(row.get("gas_quote_raw")) for row in selected)
        unrealized_values = [
            _optional_int(row.get("unrealized_quote_raw")) for row in selected
        ]
        unrealized_known = all(value is not None for value in unrealized_values)
        unrealized_raw = (
            sum(value for value in unrealized_values if value is not None)
            if unrealized_known
            else None
        )
        roi_net_raw = (
            sale_pnl_raw + unrealized_raw - gas_raw
            if unrealized_raw is not None
            else None
        )
        retained = sum((_float(row.get("tokens_end")) or 0.0) > 0 for row in selected)
        fee_rows = [fee_map.get(wallet) for wallet in assigned if wallet in fee_map]
        fee_volume = sum(_float(row.get("volume_eth")) or 0.0 for row in fee_rows)
        total_fee = sum(_float(row.get("total_fee_eth")) or 0.0 for row in fee_rows)
        rows.append(
            {
                **data,
                "wallets": len(assigned),
                "net_quote_eth": (net_raw / 10**18 if net_raw is not None else None),
                "basis_deployed_eth": basis_raw / 10**18,
                "realized_quote_eth": realized_raw / 10**18,
                "unrealized_quote_eth": (
                    unrealized_raw / 10**18 if unrealized_raw is not None else None
                ),
                "gas_quote_eth": gas_raw / 10**18,
                "net_roi_bps": (
                    round(roi_net_raw * 10_000 / basis_raw)
                    if roi_net_raw is not None and basis_raw
                    else None
                ),
                "tokens_end": sum(
                    _float(row.get("tokens_end")) or 0.0 for row in selected
                ),
                "profitable_wallets": (
                    sum(value > 0 for value in net_values if value is not None)
                    if net_known
                    else None
                ),
                "losing_wallets": (
                    sum(value < 0 for value in net_values if value is not None)
                    if net_known
                    else None
                ),
                "flat_wallets": (
                    sum(value == 0 for value in net_values if value is not None)
                    if net_known
                    else None
                ),
                "open_wallets": sum(
                    str(row.get("open", "")).lower() == "true" for row in selected
                ),
                "retained_wallets": retained,
                "retention_bps": (
                    round(retained * 10_000 / len(assigned)) if assigned else None
                ),
                "fee_wallets": len(fee_rows),
                "fee_volume_eth": fee_volume,
                "total_fee_eth": total_fee,
                "fee_burden_bps": (
                    round(total_fee * 10_000 / fee_volume) if fee_volume else None
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["net_quote_eth"] is None,
            -(row["net_quote_eth"] or 0.0),
            row["route"],
            row["selector"],
        )
    )
    wallet_rows.sort(key=lambda row: (row["route"], row["selector"], row["wallet"]))
    routed = {row["wallet"] for row in wallet_rows}
    unassigned = sorted(set(position_map) - routed)
    total_values = [_optional_int(row.get("net_quote_raw")) for row in positions]
    total_net_known = all(value is not None for value in total_values)
    total_net_raw = (
        sum(value for value in total_values if value is not None)
        if total_net_known
        else None
    )
    total_basis_raw = sum(_int(row.get("basis_deployed_raw")) for row in positions)
    total_unrealized_values = [
        _optional_int(row.get("unrealized_quote_raw")) for row in positions
    ]
    total_unrealized_raw = (
        sum(value for value in total_unrealized_values if value is not None)
        if all(value is not None for value in total_unrealized_values)
        else None
    )
    summary = {
        "profile": profile.name,
        "minutes": minutes,
        "scope": (
            "wallet outcome joined to the route of its first launch buy; "
            "transfer and gas-only entrants are not assigned a route"
        ),
        "routes": len(rows),
        "wallets": len(wallet_rows),
        "unassigned_wallets": len(unassigned),
        "unassigned_net_quote_eth": (
            sum(
                _int(position_map[wallet].get("net_quote_raw")) for wallet in unassigned
            )
            / 10**18
            if all(
                position_map[wallet].get("net_quote_raw") not in (None, "")
                for wallet in unassigned
            )
            else None
        ),
        "net_quote_eth": (
            total_net_raw / 10**18 if total_net_raw is not None else None
        ),
        "basis_deployed_eth": total_basis_raw / 10**18,
        "realized_quote_eth": sum(
            _int(row.get("realized_quote_raw")) for row in positions
        )
        / 10**18,
        "unrealized_quote_eth": (
            total_unrealized_raw / 10**18 if total_unrealized_raw is not None else None
        ),
        "gas_quote_eth": sum(_int(row.get("gas_quote_raw")) for row in positions)
        / 10**18,
        "fee_wallets": len(fee_map),
        "fee_volume_eth": sum(
            _float(row.get("volume_eth")) or 0.0 for row in fee_map.values()
        ),
        "total_fee_eth": sum(
            _float(row.get("total_fee_eth")) or 0.0 for row in fee_map.values()
        ),
        "fee_burden_bps": (
            round(
                sum(_float(row.get("total_fee_eth")) or 0.0 for row in fee_map.values())
                * 10_000
                / sum(_float(row.get("volume_eth")) or 0.0 for row in fee_map.values())
            )
            if sum(_float(row.get("volume_eth")) or 0.0 for row in fee_map.values())
            else None
        ),
        "net_roi_bps": (
            round(
                (
                    sum(_int(row.get("sale_pnl_raw")) for row in positions)
                    + total_unrealized_raw
                    - sum(_int(row.get("gas_quote_raw")) for row in positions)
                )
                * 10_000
                / total_basis_raw
            )
            if total_unrealized_raw is not None and total_basis_raw
            else None
        ),
        "retained_wallets": sum(row["retained_wallets"] for row in rows),
        "retention_bps": (
            round(
                sum(row["retained_wallets"] for row in rows) * 10_000 / len(wallet_rows)
            )
            if wallet_rows
            else None
        ),
        "top_by_net": rows[:20],
        "top_by_roi": sorted(
            (row for row in rows if row["net_roi_bps"] is not None),
            key=lambda row: (
                -row["net_roi_bps"],
                -(row["net_quote_eth"] or 0.0),
                row["route"],
            ),
        )[:20],
        "top_by_fees": sorted(
            (row for row in rows if row["fee_burden_bps"] is not None),
            key=lambda row: (
                -row["fee_burden_bps"],
                -row["total_fee_eth"],
                row["route"],
            ),
        )[:20],
        "top_by_retention": sorted(
            (row for row in rows if row["retention_bps"] is not None),
            key=lambda row: (
                -row["retention_bps"],
                -(row["net_quote_eth"] or 0.0),
                row["route"],
            ),
        )[:20],
    }
    destination = output or f"analysis/route-performance-{minutes}"
    store.write_csv(f"{destination}/routes.csv", rows, fields=ROUTE_FIELDS)
    store.write_csv(f"{destination}/wallets.csv", wallet_rows, fields=WALLET_FIELDS)
    store.write_json(f"{destination}/summary.json", summary)
    return summary
