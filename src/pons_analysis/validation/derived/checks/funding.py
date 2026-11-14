"""Funding graph checks."""

from pons_analysis.validation.derived.context import ValidationContext, require_summary


def run(ctx: ValidationContext) -> None:
    funding_edges = ctx.funding_edges
    funding_wallets = ctx.funding_wallets
    funding_summary = ctx.funding_summary
    require_summary(ctx, funding_summary, funding_edges or funding_wallets, "funding")
    if funding_summary is not None:
        ctx.check(
            "funding table counts",
            len(funding_edges) == funding_summary.get("edges")
            and len(funding_wallets) == funding_summary.get("wallets"),
            "funding edge/wallet counts disagree with summary",
        )
        funding_flow = funding_summary.get("flow") or {}
        ctx.check(
            "funding summary totals",
            sum(int(row.get("gas_raw") or 0) for row in funding_wallets)
            == int(funding_flow.get("gas_raw") or 0)
            and sum(int(row.get("net_raw") or 0) for row in funding_wallets)
            == int(funding_flow.get("net_flow_raw") or 0),
            "funding summary totals disagree with edge/wallet tables",
        )
