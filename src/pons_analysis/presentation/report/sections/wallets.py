"""Wallet-centric sections: PnL, scorecard, cohorts, retention, lifecycle."""

from typing import Any

from pons_analysis.presentation.report.charts import pnl_histogram_svg
from pons_analysis.presentation.report.formatting import (
    esc,
    fmt_eth,
    fmt_num,
    short,
    table,
)


def wallet_pnl_section(data: dict[str, Any]) -> str:
    positions = data["positions"]
    totals = positions["summary"].get("totals") or {}
    performance = positions["summary"].get("performance") or {}
    distribution = positions["summary"].get("pnl_distribution") or {}
    inventory_age = positions["summary"].get("inventory_age") or {}
    lot_extremes = positions["summary"].get("lot_extremes") or {}
    age_buckets = positions["summary"].get("inventory_age_buckets") or []
    position_rows = [
        [
            short(row["wallet"]),
            "•" if row["cohort"] else "",
            fmt_num(row.get("tokens_end")),
            fmt_eth(row.get("realized_quote_eth")),
            fmt_eth(row.get("unrealized_quote_eth")),
            fmt_eth(row.get("gas_quote_eth")),
            fmt_eth(row.get("net_quote_eth")),
            fmt_num(row.get("net_roi_bps"), 0)
            if row.get("net_roi_bps") is not None
            else "—",
            fmt_num(row.get("holding_seconds"), 0)
            if row.get("holding_seconds") is not None
            else "—",
        ]
        for row in positions["top_wallets"]
    ]
    worst_lot_rows = [
        [
            short(row["wallet"]),
            row.get("age_seconds", 0),
            fmt_eth(row.get("cost_eth")),
            fmt_eth(row.get("mark_value_eth")),
            fmt_eth(row.get("unrealized_pnl_eth")),
        ]
        for row in (lot_extremes.get("worst_unrealized") or [])[:5]
    ]
    best_lot_rows = [
        [
            short(row["wallet"]),
            row.get("age_seconds", 0),
            fmt_eth(row.get("cost_eth")),
            fmt_eth(row.get("mark_value_eth")),
            fmt_eth(row.get("unrealized_pnl_eth")),
        ]
        for row in (lot_extremes.get("best_unrealized") or [])[:5]
    ]
    age_bucket_rows = [
        [
            row.get("bucket", ""),
            row.get("lots", 0),
            fmt_num(row.get("tokens"), 2),
            fmt_eth(row.get("cost_eth")),
            fmt_eth(row.get("mark_value_eth")),
            fmt_eth(row.get("unrealized_pnl_eth")),
        ]
        for row in age_buckets
    ]
    age_bucket_html = (
        "<h3>Remaining inventory by age</h3>"
        + table(
            ["Bucket", "Lots", "Tokens", "Cost ETH", "Mark ETH", "Unrealized ETH"],
            age_bucket_rows,
            numeric_from=1,
        )
        if age_bucket_rows
        else ""
    )
    lot_extremes_html = (
        "<h3>Largest unrealized lot losses</h3>"
        + table(
            ["Wallet", "Age s", "Cost ETH", "Mark ETH", "Unrealized ETH"],
            worst_lot_rows,
            numeric_from=1,
        )
        if worst_lot_rows
        else ""
    ) + (
        "<h3>Largest unrealized lot gains</h3>"
        + table(
            ["Wallet", "Age s", "Cost ETH", "Mark ETH", "Unrealized ETH"],
            best_lot_rows,
            numeric_from=1,
        )
        if best_lot_rows
        else ""
    )
    return f"""\
<section>
  <h2>Wallet PnL</h2>
  <p class="muted">Realized {fmt_eth(totals.get("realized_quote_eth"))} ETH ·
  unrealized {fmt_eth(totals.get("unrealized_quote_eth"))} ETH ·
  gas {fmt_eth(totals.get("gas_quote_eth"))} ETH ·
  net {fmt_eth(totals.get("net_quote_eth"))} ETH ·
  {positions["summary"].get("transactions", 0)} transactions ·
  {positions["summary"].get("multi_swap_transactions", 0)} multi-swap ·
  {positions["summary"].get("resolved_intermediary_legs", 0)} router-resolved legs ·
  {inventory_age.get("remaining_lots", 0)} remaining lots ·
  median lot age {inventory_age.get("median_wallet_lot_age_seconds") if inventory_age.get("median_wallet_lot_age_seconds") is not None else "—"}s ·
  oldest {inventory_age.get("oldest_lot_age_seconds") if inventory_age.get("oldest_lot_age_seconds") is not None else "—"}s</p>
  <p class="muted">Profit factor
  {("∞" if distribution.get("profit_factor_unbounded") else (f"{distribution['profit_factor']:.2f}x" if distribution.get("profit_factor") is not None else "—"))} ·
  median net {fmt_eth(distribution.get("median_net_eth"))} ETH ·
  p10 / p90 {fmt_eth(distribution.get("p10_net_eth"))} /
  {fmt_eth(distribution.get("p90_net_eth"))} ETH ·
  top-10 profit share {distribution.get("top10_profit_share_bps") if distribution.get("top10_profit_share_bps") is not None else "—"} bps</p>
  {pnl_histogram_svg(distribution.get("histogram") or [])}
  {lot_extremes_html}
  {age_bucket_html}
  <p class="muted">Wallet ROI
  {performance.get("net_roi_bps") if performance.get("net_roi_bps") is not None else "—"} bps ·
  realized ROI
  {performance.get("realized_roi_bps") if performance.get("realized_roi_bps") is not None else "—"} bps ·
  {performance.get("profitable_wallets") if performance.get("profitable_wallets") is not None else "—"} profitable /
  {performance.get("losing_wallets") if performance.get("losing_wallets") is not None else "—"} losing ·
  median ROI
  {performance.get("median_wallet_roi_bps") if performance.get("median_wallet_roi_bps") is not None else "—"} bps ·
  median hold
  {performance.get("median_holding_seconds") if performance.get("median_holding_seconds") is not None else "—"}s ·
  {performance.get("open_wallets", 0)} open /
  {performance.get("closed_wallets", 0)} closed</p>
  {table(["Wallet", "Cohort", "Tokens end", "Realized ETH", "Unrealized ETH", "Gas ETH", "Net ETH", "ROI bps", "Hold s"], position_rows)}
  <p class="muted">{esc(performance.get("scope", ""))}</p>
</section>"""


def wallet_scorecard_section(data: dict[str, Any]) -> str:
    wallet_scorecard = data.get("wallet_scorecard")
    wallet_scorecard_html = ""
    if wallet_scorecard:
        scorecard_rows = [
            [
                short(row["wallet"]),
                row.get("cluster_id", ""),
                row.get("entry_phase", ""),
                fmt_eth(row.get("net_quote_eth")),
                fmt_num(row.get("net_roi_bps"), 0)
                if row.get("net_roi_bps") is not None
                else "—",
                fmt_eth(row.get("total_fee_eth")),
                fmt_num(row.get("execution_weighted_bps"), 0)
                if row.get("execution_weighted_bps") is not None
                else "—",
                "•" if row.get("prefunded") is True else "",
            ]
            for row in (wallet_scorecard.get("top_by_net") or [])[:15]
        ]
        retention_rows = [
            [
                short(row["wallet"]),
                row.get("entry_phase", ""),
                fmt_eth(row.get("net_quote_eth")),
                fmt_num(row.get("net_roi_bps"), 0)
                if row.get("net_roi_bps") is not None
                else "—",
                fmt_num(row.get("token_retention_bps"), 0)
                if row.get("token_retention_bps") is not None
                else "—",
            ]
            for row in (wallet_scorecard.get("top_by_retention") or [])[:10]
        ]
        retention_html = (
            "<h3>Top wallets by token retention</h3>"
            + table(
                ["Wallet", "Entry", "Net ETH", "ROI bps", "Retention bps"],
                retention_rows,
                numeric_from=2,
            )
            if retention_rows
            else ""
        )
        wallet_scorecard_html = f"""
        <section>
          <h2>Wallet scorecard</h2>
          <p class="muted">{wallet_scorecard.get("wallets", 0)} wallets ·
          {wallet_scorecard.get("profitable_wallets") if wallet_scorecard.get("profitable_wallets") is not None else "—"} profitable /
          {wallet_scorecard.get("losing_wallets") if wallet_scorecard.get("losing_wallets") is not None else "—"} losing ·
          net {fmt_eth(wallet_scorecard.get("net_quote_eth"))} ETH ·
          ROI {wallet_scorecard.get("net_roi_bps") if wallet_scorecard.get("net_roi_bps") is not None else "—"} bps ·
          fees {fmt_eth(wallet_scorecard.get("total_fee_eth"))} ETH ·
          impact {wallet_scorecard.get("execution_weighted_bps") if wallet_scorecard.get("execution_weighted_bps") is not None else "—"} bps ·
          route {wallet_scorecard.get("route_wallets", 0)} /
          retention {wallet_scorecard.get("retention_wallets", 0)} wallets</p>
          {table(["Wallet", "Cluster", "Entry", "Net ETH", "ROI bps", "Fee ETH", "Impact bps", "Prefunded"], scorecard_rows, numeric_from=3)}
          {retention_html}
        </section>
        """

    return wallet_scorecard_html


def entry_cohorts_section(data: dict[str, Any]) -> str:
    entry_cohorts = data.get("entry_cohorts")
    entry_cohorts_html = ""
    if entry_cohorts:
        cohort_rows = [
            [
                str(row.get("start_utc", ""))[11:19],
                row.get("wallets", 0),
                row.get("open_wallets", 0),
                row.get("closed_wallets", 0),
                fmt_eth(row.get("net_quote_eth")),
                row.get("roi_bps") if row.get("roi_bps") is not None else "—",
                fmt_num(row.get("median_holding_seconds"), 0)
                if row.get("median_holding_seconds") is not None
                else "—",
            ]
            for row in (entry_cohorts.get("top_by_net") or [])[:12]
        ]
        entry_cohorts_html = f"""
        <section>
          <h2>Entry-time cohorts</h2>
          <p class="muted">{entry_cohorts.get("wallets", 0)} wallets in
          {entry_cohorts.get("cohorts", 0)} UTC entry buckets ·
          {entry_cohorts.get("unbucketable_wallets", 0)} gas-only/unbucketable
          ({fmt_eth(entry_cohorts.get("unbucketable_net_quote_eth"))} ETH net) ·
          first {str(entry_cohorts.get("first_entry_utc", ""))[11:19]} ·
          last {str(entry_cohorts.get("last_entry_utc", ""))[11:19]}</p>
          {table(["Entry", "Wallets", "Open", "Closed", "Net ETH", "ROI bps", "Median hold s"], cohort_rows, numeric_from=1)}
          <p class="muted">Cohorts group wallets by first observed token activity; gas-only wallets are excluded.</p>
        </section>
        """

    return entry_cohorts_html


def retention_section(data: dict[str, Any]) -> str:
    retention = data.get("retention")
    retention_html = ""
    if retention:
        retention_rows = [
            [
                str(row.get("entry_utc", ""))[11:19],
                row.get("wallets", 0),
                row.get("wallets_remaining", 0),
                fmt_num(row.get("initial_tokens")),
                fmt_num(row.get("tokens_remaining")),
                row.get("token_retention_bps")
                if row.get("token_retention_bps") is not None
                else "—",
                row.get("holder_retention_bps")
                if row.get("holder_retention_bps") is not None
                else "—",
            ]
            for row in (retention.get("top_by_retention") or [])[:12]
        ]
        retention_html = f"""
        <section>
          <h2>Cohort retention</h2>
          <p class="muted">{retention.get("cohorts", 0)} entry cohorts ·
          {retention.get("wallets", 0)} wallets ·
          {retention.get("wallets_remaining", 0)} still holding ·
          token retention {retention.get("token_retention_bps") if retention.get("token_retention_bps") is not None else "—"} bps ·
          holder retention {retention.get("holder_retention_bps") if retention.get("holder_retention_bps") is not None else "—"} bps</p>
          {table(["Entry", "Wallets", "Holders left", "Initial tokens", "Remaining tokens", "Token retention bps", "Holder retention bps"], retention_rows, numeric_from=1)}
          <p class="muted">Token retention can exceed 10,000 bps when a cohort receives additional tokens. Protocol addresses are excluded.</p>
        </section>
        """

    return retention_html


def cohort_section(data: dict[str, Any]) -> str:
    cohort = data.get("cohort")
    cohort_html = ""
    if cohort:
        generation_rows = [
            [
                row["generation"],
                row["wallets"],
                row["terminal_holders"],
                fmt_num(row.get("tokens_end")),
                fmt_eth(row.get("realized_quote_eth")),
                fmt_eth(row.get("unrealized_quote_eth")),
                fmt_eth(row.get("net_quote_eth")),
            ]
            for row in (cohort.get("generation_rows") or [])
        ]
        terminal_rows = [
            [
                short(row["wallet"]),
                row["generation"],
                row["relation"],
                fmt_num(row.get("tokens_end")),
                fmt_eth(row.get("unrealized_quote_eth")),
                fmt_eth(row.get("net_quote_eth")),
            ]
            for row in (cohort.get("top_terminal_holders") or [])
        ]
        cohort_html = f"""
        <section>
          <h2>Launch-to-exit cohort</h2>
          <p class="muted">{len(cohort.get("top_terminal_holders") or [])} shown terminal holders ·
          {cohort.get("generations", 0)} generations · top concentration
          {cohort.get("terminal_concentration_bps", 0)} bps</p>
          {table(["Gen", "Wallets", "Terminal", "Tokens end", "Realized", "Unrealized", "Net"], generation_rows, numeric_from=0)}
          {table(["Wallet", "Gen", "Relation", "Tokens", "Unrealized", "Net"], terminal_rows, numeric_from=3)}
        </section>
        """

    return cohort_html


def lifecycle_section(data: dict[str, Any]) -> str:
    lifecycle = data.get("lifecycle")
    lifecycle_html = ""
    if lifecycle:
        phase_rows = [
            [
                row["entry_phase"],
                row["wallets"],
                row["open_wallets"],
                row["closed_wallets"],
                fmt_num(row.get("tokens_end")),
                fmt_eth(row.get("capital_deployed_eth")),
                fmt_eth(row.get("net_quote_eth")),
                row.get("net_roi_bps") if row.get("net_roi_bps") is not None else "—",
                row.get("median_holding_seconds")
                if row.get("median_holding_seconds") is not None
                else "—",
            ]
            for row in (lifecycle.get("phases") or [])
        ]
        group_rows = [
            [
                row["entry_phase"],
                row["status"],
                row["wallets"],
                fmt_eth(row.get("capital_deployed_eth")),
                fmt_eth(row.get("net_quote_eth")),
                row.get("net_roi_bps") if row.get("net_roi_bps") is not None else "—",
                row.get("median_holding_seconds")
                if row.get("median_holding_seconds") is not None
                else "—",
            ]
            for row in (lifecycle.get("groups") or [])
        ]
        lifecycle_totals = lifecycle.get("totals") or {}
        lifecycle_html = f"""
        <section>
          <h2>Wallet lifecycle</h2>
          <p class="muted">{lifecycle.get("wallets", 0)} wallets ·
          {lifecycle_totals.get("open_wallets", 0)} open /
          {lifecycle_totals.get("closed_wallets", 0)} closed ·
          {fmt_eth(lifecycle_totals.get("capital_deployed_eth"))} ETH capital ·
          {fmt_eth(lifecycle_totals.get("net_quote_eth"))} ETH net ·
          {lifecycle_totals.get("net_roi_bps") if lifecycle_totals.get("net_roi_bps") is not None else "—"} bps ROI ·
          {lifecycle_totals.get("median_holding_seconds") if lifecycle_totals.get("median_holding_seconds") is not None else "—"}s median hold</p>
          <h3>Entry phases</h3>
          {table(["Phase", "Wallets", "Open", "Closed", "Tokens end", "Capital ETH", "Net ETH", "ROI bps", "Median hold s"], phase_rows, numeric_from=1)}
          <h3>Entry phase and exit status</h3>
          {table(["Phase", "Status", "Wallets", "Capital ETH", "Net ETH", "ROI bps", "Median hold s"], group_rows, numeric_from=2)}
          <p class="muted">{esc(lifecycle.get("roi_scope", ""))}</p>
        </section>
        """

    return lifecycle_html
