"""Fee ledger and aggregation checks."""

from pons_analysis.validation.derived.context import ValidationContext, require_summary


def run(ctx: ValidationContext) -> None:
    fees = ctx.fee_wallets
    fee_summary = ctx.summaries.get("fees")
    require_summary(ctx, fee_summary, fees, "fee")
    fee_totals = (fee_summary or {}).get("totals") or {}
    total_trades = sum(int(row.get("trades") or 0) for row in fees)
    if fee_summary is not None:
        ctx.check(
            "fee trade totals",
            fee_totals.get("trades") == total_trades,
            f"{total_trades} != {fee_totals.get('trades')}",
        )
        ctx.check(
            "fee group count",
            len(ctx.fee_groups) == len(fee_summary.get("groups") or []),
            "fee group table disagrees with summary",
        )
    if fees:
        ctx.subset("fee", fees)
        trade_legs = ctx.trade_legs
        if trade_legs and fee_totals:
            ctx.check(
                "fee ledger totals",
                len(trade_legs) == fee_totals.get("trades")
                and sum(int(row.get("quote_gross_raw") or 0) for row in trade_legs)
                == int(fee_totals.get("volume_raw") or 0)
                and sum(int(row.get("fee_quote_raw") or 0) for row in trade_legs)
                == int(fee_totals.get("fee_quote_raw") or 0)
                and sum(int(row.get("tax_quote_raw") or 0) for row in trade_legs)
                == int(fee_totals.get("tax_quote_raw") or 0)
                and sum(int(row.get("fee_token_raw") or 0) for row in trade_legs)
                == int(fee_totals.get("token_fee_raw") or 0)
                and sum(int(row.get("tax_token_raw") or 0) for row in trade_legs)
                == int(fee_totals.get("token_tax_raw") or 0),
                "fee summary totals differ from trade legs",
            )
            fee_groups = ctx.fee_groups
            group_fields = (
                "trades",
                "volume_raw",
                "fee_quote_raw",
                "tax_quote_raw",
                "token_fee_raw",
                "token_tax_raw",
                "token_fee_value_raw",
                "token_tax_value_raw",
                "total_fee_raw",
            )
            group_mismatches = []
            for dimension in ("all", "side", "phase"):
                selected = [
                    row for row in fee_groups if row.get("dimension") == dimension
                ]
                for field in group_fields:
                    expected = int(fee_totals.get(field) or 0)
                    if dimension == "all":
                        actual = int(selected[0].get(field) or 0) if selected else None
                    else:
                        actual = sum(int(row.get(field) or 0) for row in selected)
                    if actual != expected:
                        group_mismatches.append(f"{dimension}:{field}")
            ctx.check(
                "fee group aggregates",
                not group_mismatches,
                ", ".join(group_mismatches[:5]),
            )
            ctx.check(
                "fee wallet totals",
                sum(int(row.get("volume_raw") or 0) for row in fees)
                == int(fee_totals.get("volume_raw") or 0)
                and sum(int(row.get("fee_quote_raw") or 0) for row in fees)
                == int(fee_totals.get("fee_quote_raw") or 0)
                and sum(int(row.get("tax_quote_raw") or 0) for row in fees)
                == int(fee_totals.get("tax_quote_raw") or 0)
                and sum(int(row.get("token_fee_raw") or 0) for row in fees)
                == int(fee_totals.get("token_fee_raw") or 0)
                and sum(int(row.get("token_tax_raw") or 0) for row in fees)
                == int(fee_totals.get("token_tax_raw") or 0)
                and sum(int(row.get("token_fee_value_raw") or 0) for row in fees)
                == int(fee_totals.get("token_fee_value_raw") or 0)
                and sum(int(row.get("token_tax_value_raw") or 0) for row in fees)
                == int(fee_totals.get("token_tax_value_raw") or 0)
                and sum(int(row.get("total_fee_raw") or 0) for row in fees)
                == int(fee_totals.get("total_fee_raw") or 0),
                "fee wallet totals differ from fee summary",
            )
