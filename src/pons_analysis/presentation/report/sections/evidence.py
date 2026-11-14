"""Execution, cluster, fee, funding, and provenance sections."""

from typing import Any

from pons_analysis.presentation.report.formatting import (
    esc,
    fmt_eth,
    fmt_num,
    short,
    table,
)


def route_performance_section(data: dict[str, Any]) -> str:
    route_performance = data.get("route_performance")
    route_performance_html = ""
    if route_performance:
        performance_rows = [
            [
                row.get("route_short", ""),
                row.get("selector", ""),
                row.get("wallets", 0),
                row.get("retained_wallets", 0),
                fmt_eth(row.get("launch_buy_volume_eth")),
                fmt_eth(row.get("net_quote_eth")),
                fmt_eth(row.get("total_fee_eth")),
                row.get("fee_burden_bps")
                if row.get("fee_burden_bps") is not None
                else "—",
                row.get("net_roi_bps") if row.get("net_roi_bps") is not None else "—",
                (
                    f"{row.get('profitable_wallets')}/{row.get('losing_wallets')}"
                    if row.get("profitable_wallets") is not None
                    and row.get("losing_wallets") is not None
                    else "—"
                ),
            ]
            for row in (route_performance.get("top_by_net") or [])[:10]
        ]
        fee_route_rows = [
            [
                row.get("route_short", ""),
                row.get("selector", ""),
                row.get("wallets", 0),
                fmt_eth(row.get("net_quote_eth")),
                fmt_eth(row.get("total_fee_eth")),
                row.get("fee_burden_bps")
                if row.get("fee_burden_bps") is not None
                else "—",
            ]
            for row in (route_performance.get("top_by_fees") or [])[:5]
        ]
        retention_route_rows = [
            [
                row.get("route_short", ""),
                row.get("selector", ""),
                row.get("wallets", 0),
                fmt_eth(row.get("net_quote_eth")),
                row.get("retained_wallets", 0),
                row.get("retention_bps")
                if row.get("retention_bps") is not None
                else "—",
            ]
            for row in (route_performance.get("top_by_retention") or [])[:5]
        ]
        route_performance_html = f"""
        <section>
          <h2>Launch route wallet performance</h2>
          <p class="muted">{route_performance.get("routes", 0)} routes ·
          {route_performance.get("wallets", 0)} routed wallets ·
          {route_performance.get("unassigned_wallets", 0)} unassigned ·
          realized {fmt_eth(route_performance.get("realized_quote_eth"))} ETH ·
          unrealized {fmt_eth(route_performance.get("unrealized_quote_eth"))} ETH ·
          gas {fmt_eth(route_performance.get("gas_quote_eth"))} ETH ·
          net {fmt_eth(route_performance.get("net_quote_eth"))} ETH ·
          ROI {route_performance.get("net_roi_bps") if route_performance.get("net_roi_bps") is not None else "—"} bps ·
          fees {fmt_eth(route_performance.get("total_fee_eth"))} ETH ·
          burden {route_performance.get("fee_burden_bps") if route_performance.get("fee_burden_bps") is not None else "—"} bps ·
          retained {route_performance.get("retained_wallets", 0)} wallets
          ({route_performance.get("retention_bps") if route_performance.get("retention_bps") is not None else "—"} bps)</p>
          {table(["Route", "Selector", "Wallets", "Retained", "Launch ETH", "Net ETH", "Fee ETH", "Burden bps", "ROI bps", "Win/Loss"], performance_rows, numeric_from=2)}
          <h3>Top routes by fee burden</h3>
          {table(["Route", "Selector", "Wallets", "Net ETH", "Fee ETH", "Burden bps"], fee_route_rows, numeric_from=2)}
          <h3>Top routes by retention</h3>
          {table(["Route", "Selector", "Wallets", "Net ETH", "Retained", "Ret bps"], retention_route_rows, numeric_from=2)}
          <p class="muted">{esc(route_performance.get("scope", ""))}</p>
        </section>
        """
    return route_performance_html


def execution_section(data: dict[str, Any]) -> str:
    execution = data.get("execution")
    execution_html = ""
    if execution:
        execution_groups = [
            [
                row["dimension"],
                row["value"],
                row.get("trades", 0),
                fmt_eth(row.get("volume_eth")),
                row.get("median_abs_bps")
                if row.get("median_abs_bps") is not None
                else "—",
                row.get("p90_abs_bps") if row.get("p90_abs_bps") is not None else "—",
                row.get("max_abs_bps") if row.get("max_abs_bps") is not None else "—",
                row.get("volume_weighted_abs_bps")
                if row.get("volume_weighted_abs_bps") is not None
                else "—",
            ]
            for row in (execution.get("groups") or [])
        ]
        execution_wallets = [
            [
                short(row["wallet"]),
                row.get("trades", 0),
                fmt_eth(row.get("volume_eth")),
                row.get("median_abs_bps")
                if row.get("median_abs_bps") is not None
                else "—",
                row.get("p90_abs_bps") if row.get("p90_abs_bps") is not None else "—",
                row.get("max_abs_bps") if row.get("max_abs_bps") is not None else "—",
                row.get("volume_weighted_abs_bps")
                if row.get("volume_weighted_abs_bps") is not None
                else "—",
            ]
            for row in (execution.get("top_by_weighted") or [])[:10]
        ]
        execution_html = f"""
        <section>
          <h2>Wallet execution impact</h2>
          <p class="muted">{execution.get("wallets", 0)} wallets ·
          {execution.get("attributed_trades", 0)} / {execution.get("impact_trades", 0)} impact trades attributed ·
          {execution.get("coverage_bps") if execution.get("coverage_bps") is not None else "—"} bps coverage ·
          {execution.get("unattributed_trades", 0)} unattributed ·
          median abs {execution.get("median_abs_bps") if execution.get("median_abs_bps") is not None else "—"} bps ·
          p90 abs {execution.get("p90_abs_bps") if execution.get("p90_abs_bps") is not None else "—"} bps ·
          volume-weighted {execution.get("volume_weighted_abs_bps") if execution.get("volume_weighted_abs_bps") is not None else "—"} bps</p>
          <h3>Impact groups</h3>
          {table(["Dimension", "Value", "Trades", "Volume ETH", "Median abs bps", "P90 abs bps", "Max abs bps", "Vol-weighted bps"], execution_groups, numeric_from=2)}
          <h3>Top wallets</h3>
          {table(["Wallet", "Trades", "Volume ETH", "Median abs bps", "P90 abs bps", "Max abs bps", "Vol-weighted bps"], execution_wallets, numeric_from=1)}
          <p class="muted">{esc(execution.get("scope", ""))}</p>
        </section>
        """

    return execution_html


def cluster_quality_section(data: dict[str, Any]) -> str:
    cluster_quality = data.get("cluster_quality")
    cluster_quality_html = ""
    if cluster_quality:
        quality_rows = [
            [
                row["cluster_id"].replace("cluster-", "c"),
                row.get("wallets", 0),
                row.get("execution_wallets", 0),
                fmt_eth(row.get("execution_volume_eth")),
                row.get("execution_weighted_bps")
                if row.get("execution_weighted_bps") is not None
                else "—",
                fmt_eth(row.get("total_fee_eth")),
                row.get("fee_burden_bps")
                if row.get("fee_burden_bps") is not None
                else "—",
                fmt_eth(row.get("net_quote_eth")),
                row.get("net_roi_bps") if row.get("net_roi_bps") is not None else "—",
                (
                    f"{row['roi_p25_bps']}..{row['roi_p75_bps']}"
                    if row.get("roi_p25_bps") is not None
                    and row.get("roi_p75_bps") is not None
                    else "—"
                ),
                row.get("fresh_wallets", 0),
            ]
            for row in sorted(
                (cluster_quality.get("rows") or []),
                key=lambda item: (
                    -(item.get("execution_weighted_bps") or -1),
                    item["cluster_id"],
                ),
            )[:12]
        ]
        cluster_quality_html = f"""
        <section>
          <h2>Cluster execution and fees</h2>
          <p class="muted">{cluster_quality.get("clusters", 0)} clusters ·
          {cluster_quality.get("wallets", 0)} clustered wallets ·
          {cluster_quality.get("execution_wallets", 0)} with execution data ·
          weighted impact {cluster_quality.get("execution_weighted_bps") if cluster_quality.get("execution_weighted_bps") is not None else "—"} bps ·
          fee burden {cluster_quality.get("fee_burden_bps") if cluster_quality.get("fee_burden_bps") is not None else "—"} bps ·
          gas {fmt_eth(cluster_quality.get("gas_eth"))} ETH ·
          {cluster_quality.get("profitable_wallets") if cluster_quality.get("profitable_wallets") is not None else "—"} profitable /
          {cluster_quality.get("losing_wallets") if cluster_quality.get("losing_wallets") is not None else "—"} losing wallets</p>
          {table(["Cluster", "Wallets", "Exec", "Exec ETH", "Impact bps", "Fee ETH", "Burden bps", "Net ETH", "ROI bps", "ROI p25..p75", "Fresh"], quality_rows, numeric_from=1)}
          <p class="muted">{esc(cluster_quality.get("scope", ""))}</p>
        </section>
        """

    return cluster_quality_html


def clusters_section(data: dict[str, Any]) -> str:
    clusters = data.get("clusters")
    clusters_html = ""
    if clusters:
        cluster_rows = [
            [
                row["cluster_id"].replace("cluster-", "c"),
                row["wallets"],
                fmt_num(row.get("tokens_end")),
                fmt_eth(row.get("realized_quote_eth")),
                fmt_eth(row.get("unrealized_quote_eth")),
                fmt_eth(row.get("net_quote_eth")),
                row["timing_edges"],
            ]
            for row in (clusters.get("top_clusters") or [])
        ]
        behavior_rows = [
            [
                row["cluster_id"].replace("cluster-", "c"),
                row["round_trips"],
                "—" if row.get("win_rate") is None else f"{row['win_rate'] * 100:.1f}%",
                row["same_block_round_trips"],
                fmt_num(row.get("median_hold_seconds"), 0),
                fmt_eth(row.get("trade_round_trip_pnl_eth")),
            ]
            for row in (clusters.get("top_clusters") or [])
        ]
        funder_rows = [
            [
                short(row["source"]),
                len(row.get("members") or []),
                fmt_eth(row.get("value_eth")),
                "•" if row.get("source_in_core") else "",
            ]
            for row in (clusters.get("shared_funders") or [])
        ]
        behavior = clusters.get("behavior") or {}
        funder_html = (
            "<h3>Shared funders</h3>"
            + table(
                ["Funder", "Wallets", "Value ETH", "Core"],
                funder_rows,
                numeric_from=1,
            )
            if funder_rows
            else ""
        )
        clusters_html = f"""
        <section>
          <h2>Cluster and timing evidence</h2>
          <p class="muted">{clusters.get("clusters", 0)} clusters ·
          {clusters.get("clustered_wallets", 0)} clustered wallets ·
          {clusters.get("singleton_wallets", 0)} singletons ·
          {(clusters.get("edges") or {}).get("timing", 0)} timing links ·
          {behavior.get("round_trips", 0)} round trips ·
          {fmt_num(behavior.get("median_hold_seconds"), 0)}s median hold ·
          {fmt_eth(behavior.get("trade_round_trip_pnl_eth"))} ETH trade-only PnL ·
          {fmt_num(behavior.get("unmatched_sell_tokens"))} unmatched tokens</p>
          <h3>Cluster PnL</h3>
          {table(["Cluster", "Wallets", "Tokens end", "Realized", "Unrealized", "Net", "Timing"], cluster_rows, numeric_from=1)}
          <h3>Round-trip behavior</h3>
          {table(["Cluster", "Round trips", "Win %", "Same block", "Hold s", "Trade PnL"], behavior_rows, numeric_from=1)}
          {funder_html}
          <p class="muted">{esc(clusters.get("method_note", ""))}</p>
        </section>
        """

    return clusters_html


def fees_section(data: dict[str, Any]) -> str:
    fees = data.get("fees")
    fees_html = ""
    if fees:
        fee_totals = fees.get("totals") or {}
        group_rows = [
            [
                row["dimension"],
                row["value"],
                row["trades"],
                fmt_eth(row.get("volume_eth")),
                fmt_eth(row.get("total_fee_eth")),
                row["fee_burden_bps"] if row.get("fee_burden_bps") is not None else "—",
            ]
            for row in (fees.get("groups") or [])
        ]
        wallet_rows = [
            [
                short(row["wallet"]),
                row["trades"],
                fmt_eth(row.get("volume_eth")),
                fmt_eth(row.get("fee_quote_eth")),
                fmt_eth(row.get("token_fee_value_eth")),
                fmt_eth(row.get("total_fee_eth")),
                row["fee_burden_bps"] if row.get("fee_burden_bps") is not None else "—",
            ]
            for row in (fees.get("top_wallets") or [])[:10]
        ]
        fees_html = f"""
        <section>
          <h2>Fees and taxes</h2>
          <p class="muted">{fee_totals.get("trades", 0)} trades ·
          {fmt_eth(fee_totals.get("volume_eth"))} ETH gross volume ·
          quote fee {fmt_eth(fee_totals.get("fee_quote_eth"))} ETH ·
          creator tax {fmt_eth(fee_totals.get("tax_quote_eth"))} ETH ·
          token fee value {fmt_eth(fee_totals.get("token_fee_value_eth"))} ETH ·
          token tax value {fmt_eth(fee_totals.get("token_tax_value_eth"))} ETH ·
          total {fmt_eth(fee_totals.get("total_fee_eth"))} ETH ·
          burden {fee_totals.get("fee_burden_bps") if fee_totals.get("fee_burden_bps") is not None else "—"} bps</p>
          <h3>Fee groups</h3>
          {table(["Dimension", "Value", "Trades", "Gross volume", "Fee ETH", "Burden bps"], group_rows, numeric_from=2)}
          <h3>Top fee payers</h3>
          {table(["Wallet", "Trades", "Gross volume", "Quote fee", "Token fee value", "Total", "Burden bps"], wallet_rows, numeric_from=1)}
          <p class="muted">{esc(fees.get("fee_scope", ""))} · {esc(fees.get("fee_quote_note", ""))} · {esc(fees.get("token_fee_valuation", ""))}</p>
        </section>
        """

    return fees_html


def funding_section(data: dict[str, Any]) -> str:
    funding = data.get("funding")
    funding_html = ""
    if funding:
        funders = (funding.get("counterparties") or {}).get("funders") or []
        hubs = funding.get("fanout_hubs") or []
        fresh = funding.get("fresh_wallets") or []
        funder_rows = [
            [short(row["address"]), fmt_eth(row.get("value_eth")), row["edges"]]
            for row in funders
        ]
        hub_rows = [
            [
                short(row["source"]),
                "•" if row.get("source_in_core") else "",
                row["recipients"],
                fmt_eth(row.get("value_eth")),
            ]
            for row in hubs
        ]
        fresh_rows = [
            [
                short(row["wallet"]),
                row["nonce"],
                fmt_eth(row.get("balance_eth")),
                fmt_eth(row.get("inbound_eth")),
                row["transactions"],
            ]
            for row in fresh
        ]
        funding_html = f"""
        <section>
          <h2>Native funding graph</h2>
          <p class="muted">{funding.get("wallets", 0)} wallets ·
          {funding.get("transactions", 0)} transactions ·
          {funding.get("internal_transfers", 0)} internal transfers ·
          {funding.get("edges", 0)} edges</p>
          <h3>Top external funders</h3>
          {table(["Funder", "Value ETH", "Edges"], funder_rows, numeric_from=1)}
          <h3>Fan-out hubs</h3>
          {table(["Source", "Core", "Recipients", "Value ETH"], hub_rows, numeric_from=2)}
          <h3>Fresh wallets</h3>
          {table(["Wallet", "Nonce", "Balance", "Inbound", "Txs"], fresh_rows, numeric_from=1)}
        </section>
        """

    return funding_html


def provenance_section(data: dict[str, Any]) -> str:
    provenance = data.get("provenance")
    provenance_html = ""
    if provenance:
        provenance_rows = [
            [
                short(row["wallet"]),
                row.get("cluster_id", ""),
                "•" if row.get("fresh") else "",
                row.get("entry_phase", ""),
                row.get("lead_seconds") if row.get("lead_seconds") is not None else "—",
                short(row.get("first_inflow_source", ""))
                if row.get("first_inflow_source")
                else "—",
                fmt_eth(row.get("first_inflow_value_eth")),
                fmt_eth(row.get("net_quote_eth")),
                "yes"
                if row.get("prefunded") is True
                else "no"
                if row.get("prefunded") is False
                else "—",
            ]
            for row in (provenance.get("rows") or [])[:15]
        ]
        source_rows = [
            [
                short(row["source"]),
                row.get("wallets", 0),
                fmt_eth(row.get("value_eth")),
            ]
            for row in (provenance.get("top_sources") or [])[:10]
        ]
        provenance_html = f"""
        <section>
          <h2>Funding provenance</h2>
          <p class="muted">{provenance.get("wallets", 0)} wallets with funding evidence ·
          {provenance.get("prefunded_wallets", 0)} prefunded before first trade ·
          {provenance.get("prefunded_bps") if provenance.get("prefunded_bps") is not None else "—"} bps prefunded ·
          median lead {provenance.get("median_prefund_lead_seconds") if provenance.get("median_prefund_lead_seconds") is not None else "—"}s ·
          max lead {provenance.get("max_prefund_lead_seconds") if provenance.get("max_prefund_lead_seconds") is not None else "—"}s</p>
          {table(["Wallet", "Cluster", "Fresh", "Entry", "Lead s", "Source", "Value ETH", "Net ETH", "Prefunded"], provenance_rows, numeric_from=4)}
          <h3>Top prefunding sources</h3>
          {table(["Source", "Wallets", "Value ETH"], source_rows, numeric_from=1)}
          <p class="muted">{esc(provenance.get("scope", ""))}</p>
        </section>
        """
    return provenance_html
