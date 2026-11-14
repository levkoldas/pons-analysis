"""Route performance checks."""

import math

from pons_analysis.validation.derived.context import ValidationContext


def _optional_float(value: object) -> float | None:
    return None if value in (None, "") else float(value)


def _same_float(left: object, right: object) -> bool:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return left_value is right_value
    return math.isclose(left_value, right_value, rel_tol=1e-9, abs_tol=1e-9)


def run(ctx: ValidationContext) -> None:
    route_rows = ctx.route_rows
    route_wallets = ctx.route_wallets
    positions = ctx.positions
    if route_rows:
        route_summary = ctx.summaries.get("route-performance", {})
        ctx.check(
            "route-performance row count",
            len(route_rows) == route_summary.get("routes"),
            f"{len(route_rows)} rows vs {route_summary.get('routes')} routes",
        )
        ctx.check(
            "route-performance wallet count",
            len(route_wallets) == route_summary.get("wallets"),
            f"{len(route_wallets)} wallets vs {route_summary.get('wallets')}",
        )
        ctx.subset("route-performance", route_wallets)
        ctx.check(
            "route-performance wallet sum",
            sum(int(row.get("wallets") or 0) for row in route_rows)
            == route_summary.get("wallets"),
            "route wallet counts disagree with routed wallet rows",
        )
        route_net_values = [
            _optional_float(row.get("net_quote_eth")) for row in route_rows
        ]
        unassigned_net = _optional_float(route_summary.get("unassigned_net_quote_eth"))
        summary_net = _optional_float(route_summary.get("net_quote_eth"))
        net_split_ok = (
            summary_net is None
            and (
                any(value is None for value in route_net_values)
                or unassigned_net is None
            )
        ) or (
            summary_net is not None
            and all(value is not None for value in route_net_values)
            and unassigned_net is not None
            and math.isclose(
                sum(value for value in route_net_values if value is not None)
                + unassigned_net,
                summary_net,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        )
        ctx.check(
            "route-performance net split",
            net_split_ok,
            "routed + unassigned net != total net",
        )
        ctx.check(
            "route-performance unassigned count",
            len(positions) - len(route_wallets)
            == route_summary.get("unassigned_wallets"),
            "positions - routed != unassigned wallets",
        )
        ctx.check(
            "route-performance net total",
            _same_float(
                route_summary.get("net_quote_eth"),
                ctx.position_totals.get("net_quote_eth"),
            ),
            "route-performance net differs from positions",
        )
        ctx.check(
            "route-performance PnL totals",
            all(
                _same_float(
                    route_summary.get(key),
                    ctx.position_totals.get(key),
                )
                for key in (
                    "realized_quote_eth",
                    "unrealized_quote_eth",
                    "gas_quote_eth",
                )
            ),
            "route PnL composition differs from positions",
        )
        position_by_wallet = {row["wallet"].lower(): row for row in positions}
        route_members: dict[tuple[str, str], list[dict[str, str]]] = {}
        for row in route_wallets:
            key = (row.get("route", "").lower(), row.get("selector", "").lower())
            position = position_by_wallet.get(row["wallet"].lower())
            if position is not None:
                route_members.setdefault(key, []).append(position)
        row_mismatches = []
        for row in route_rows:
            key = (row.get("route", "").lower(), row.get("selector", "").lower())
            members = route_members.get(key, [])
            realized = sum(float(row.get("realized_quote_raw") or 0) for row in members)
            gas = sum(float(row.get("gas_quote_raw") or 0) for row in members)
            unrealized_values = [row.get("unrealized_quote_raw") for row in members]
            unrealized = (
                sum(float(value) for value in unrealized_values)
                if all(value not in (None, "") for value in unrealized_values)
                else None
            )
            row_unrealized = row.get("unrealized_quote_eth")
            if not (
                math.isclose(
                    float(row.get("realized_quote_eth") or 0),
                    realized / 10**18,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    float(row.get("gas_quote_eth") or 0),
                    gas / 10**18,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and (
                    (row_unrealized in (None, "") and unrealized is None)
                    or (
                        row_unrealized not in (None, "")
                        and unrealized is not None
                        and math.isclose(
                            float(row_unrealized),
                            unrealized / 10**18,
                            rel_tol=1e-9,
                            abs_tol=1e-12,
                        )
                    )
                )
            ):
                row_mismatches.append(f"{row.get('route')}:{row.get('selector')}")
        ctx.check(
            "route-performance PnL rows",
            not row_mismatches,
            ", ".join(row_mismatches[:5]),
        )
        fee_summary = ctx.summaries.get("fees", {})
        fee_totals = fee_summary.get("totals") or {}
        fees = ctx.fee_wallets
        if fee_totals:
            ctx.check(
                "route-performance fee totals",
                math.isclose(
                    float(route_summary.get("total_fee_eth") or 0),
                    float(fee_totals.get("total_fee_eth") or 0),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                and math.isclose(
                    float(route_summary.get("fee_volume_eth") or 0),
                    float(fee_totals.get("volume_eth") or 0),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ),
                "route fee totals differ from fees summary",
            )
            fee_by_wallet = {row["wallet"].lower(): row for row in fees}
            route_fee_members: dict[tuple[str, str], list[str]] = {}
            for row in route_wallets:
                key = (row.get("route", "").lower(), row.get("selector", "").lower())
                route_fee_members.setdefault(key, []).append(row["wallet"].lower())
            fee_mismatches = []
            for row in route_rows:
                key = (row.get("route", "").lower(), row.get("selector", "").lower())
                members = [
                    fee_by_wallet[wallet]
                    for wallet in route_fee_members.get(key, [])
                    if wallet in fee_by_wallet
                ]
                volume = sum(float(item.get("volume_eth") or 0) for item in members)
                fee = sum(float(item.get("total_fee_eth") or 0) for item in members)
                detail = (
                    float(row.get("fee_volume_eth") or 0),
                    float(row.get("total_fee_eth") or 0),
                )
                if not (
                    math.isclose(detail[0], volume, rel_tol=1e-9, abs_tol=1e-12)
                    and math.isclose(detail[1], fee, rel_tol=1e-9, abs_tol=1e-12)
                ):
                    fee_mismatches.append(f"{row.get('route')}:{row.get('selector')}")
            ctx.check(
                "route-performance fee rows",
                not fee_mismatches,
                ", ".join(fee_mismatches[:5]),
            )
        ranking_mismatches = []
        ranking_specs = {
            "top_by_net": lambda row: (
                row.get("net_quote_eth") in (None, ""),
                -float(row.get("net_quote_eth") or 0),
                row.get("route", ""),
                row.get("selector", ""),
            ),
            "top_by_roi": lambda row: (
                -float(row.get("net_roi_bps") or 0),
                -float(row.get("net_quote_eth") or 0),
                row.get("route", ""),
            ),
            "top_by_fees": lambda row: (
                -float(row.get("fee_burden_bps") or 0),
                -float(row.get("total_fee_eth") or 0),
                row.get("route", ""),
            ),
            "top_by_retention": lambda row: (
                -float(row.get("retention_bps") or 0),
                -float(row.get("net_quote_eth") or 0),
                row.get("route", ""),
            ),
        }
        for name, key in ranking_specs.items():
            field = {
                "top_by_roi": "net_roi_bps",
                "top_by_fees": "fee_burden_bps",
                "top_by_retention": "retention_bps",
            }.get(name)
            eligible = (
                route_rows
                if field is None
                else [row for row in route_rows if row.get(field) not in (None, "")]
            )
            expected = [
                (row.get("route"), row.get("selector"))
                for row in sorted(eligible, key=key)[:20]
            ]
            ranking_rows = route_summary.get(name)
            if not isinstance(ranking_rows, list):
                ranking_rows = []
            actual = [
                (row.get("route"), row.get("selector"))
                for row in ranking_rows
                if isinstance(row, dict)
            ]
            if actual != expected:
                ranking_mismatches.append(name)
        ctx.check(
            "route-performance rankings",
            not ranking_mismatches,
            ", ".join(ranking_mismatches),
        )
        wallet_field_mismatches = []
        for row in route_wallets:
            position = position_by_wallet.get(row["wallet"].lower())
            if position is None:
                continue
            if not (
                _same_float(
                    row.get("realized_quote_eth"),
                    position.get("realized_quote_eth"),
                )
                and _same_float(
                    row.get("gas_quote_eth"),
                    position.get("gas_quote_eth"),
                )
                and _same_float(
                    row.get("unrealized_quote_eth"),
                    position.get("unrealized_quote_eth"),
                )
            ):
                wallet_field_mismatches.append(row["wallet"])
        ctx.check(
            "route-performance wallet PnL",
            not wallet_field_mismatches,
            ", ".join(wallet_field_mismatches[:5]),
        )
        retained = sum(int(row.get("retained_wallets") or 0) for row in route_rows)
        ctx.check(
            "route-performance retention",
            retained == route_summary.get("retained_wallets")
            and (
                round(retained * 10_000 / len(route_wallets)) if route_wallets else None
            )
            == route_summary.get("retention_bps"),
            "route retention rows disagree with the summary",
        )
        scorecard = ctx.scorecard
        if scorecard:
            route_by_wallet = {
                row["wallet"].lower(): (
                    row.get("route", "").lower(),
                    row.get("selector", "").lower(),
                )
                for row in route_wallets
            }
            mismatches = [
                row["wallet"]
                for row in scorecard
                if (
                    row.get("entry_route", "").lower(),
                    row.get("entry_selector", "").lower(),
                )
                != route_by_wallet.get(row["wallet"].lower(), ("", ""))
            ]
            ctx.check(
                "scorecard route join",
                not mismatches,
                ", ".join(mismatches[:5]),
            )
