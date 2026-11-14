"""Market activity sections: trajectory, candles, order flow, holders."""

from typing import Any

from pons_analysis.presentation.report.charts import (
    candle_svg,
    flow_svg,
    holder_svg,
    price_svg,
)
from pons_analysis.presentation.report.formatting import (
    esc,
    fmt_eth,
    fmt_num,
    fmt_price,
    short,
    table,
)


def trajectory_section(data: dict[str, Any]) -> str:
    trajectory = data["trajectory"]
    impact = trajectory["summary"].get("execution_impact") or {}
    impact_rows = []
    if impact.get("trades"):
        for side in ("buy", "sell"):
            row = (impact.get("by_side") or {}).get(side) or {}
            impact_rows.append(
                [
                    side,
                    row.get("trades", 0),
                    fmt_eth(row.get("volume_eth")),
                    row.get("median_abs_bps")
                    if row.get("median_abs_bps") is not None
                    else "—",
                    row.get("p90_abs_bps")
                    if row.get("p90_abs_bps") is not None
                    else "—",
                    row.get("max_abs_bps")
                    if row.get("max_abs_bps") is not None
                    else "—",
                ]
            )
    impact_html = (
        f"""
        <h3>V4 execution impact</h3>
        {table(["Side", "Trades", "Volume ETH", "Median abs bps", "P90 abs bps", "Max abs bps"], impact_rows, numeric_from=1)}
        <p class="muted">{esc(impact.get("scope", ""))}</p>
        """
        if impact_rows
        else ""
    )
    return f"""\
<section>
  <h2>Price and volume trajectory</h2>
  <p class="muted">{trajectory["summary"].get("trades", 0)} trades ·
  {trajectory["summary"].get("curve_trades", 0)} curve /
  {trajectory["summary"].get("v4_swaps", 0)} v4 ·
  first {fmt_price(trajectory["summary"].get("first_price_eth"))} ·
  last {fmt_price(trajectory["summary"].get("last_price_eth"))} ·
  max drawdown {trajectory["summary"].get("max_drawdown_bps", 0)} bps ·
  v4 impact {impact.get("trades", 0)}/{trajectory["summary"].get("v4_swaps", 0)} ·
  median abs {impact.get("median_abs_bps") if impact.get("median_abs_bps") is not None else "—"} bps ·
  p90 abs {impact.get("p90_abs_bps") if impact.get("p90_abs_bps") is not None else "—"} bps</p>
  {price_svg(data["trajectory"]["series"])}
  {impact_html}
</section>"""


def candles_section(data: dict[str, Any]) -> str:
    candles = data.get("candles")
    candles_summary = (candles or {}).get("summary") or {}
    candles_series = (candles or {}).get("series") or []
    candles_html = ""
    if candles:
        profile_rows = [
            [
                row.get("bin", ""),
                fmt_price(row.get("price_low_eth")),
                fmt_price(row.get("price_high_eth")),
                row.get("trades", 0),
                fmt_eth(row.get("volume_eth")),
                row.get("volume_share_bps", 0),
            ]
            for row in (candles_summary.get("volume_profile") or [])
        ]
        candles_html = f"""
        <section>
          <h2>OHLCV candles</h2>
          <p class="muted">{candles_summary.get("candles", 0)} candles at
          {candles_summary.get("bucket_seconds", 0)}s ·
          {candles_summary.get("partial_candles", 0)} partial ·
          {candles_summary.get("trades", 0)} trades ·
          VWAP {fmt_price(candles_summary.get("vwap_eth"))} ·
          FDV {fmt_num(candles_summary.get("fdv_last_eth"), 2)} ETH ·
          peak FDV {fmt_num(candles_summary.get("fdv_peak_eth"), 2)} ETH ·
          realized vol {candles_summary.get("realized_volatility_bps") if candles_summary.get("realized_volatility_bps") is not None else "—"} bps ·
          max range {candles_summary.get("max_range_bps") if candles_summary.get("max_range_bps") is not None else "—"} bps</p>
          {candle_svg(candles_series)}
          <h3>Volume profile</h3>
          {table(["Bin", "Price low", "Price high", "Trades", "Volume ETH", "Share bps"], profile_rows, numeric_from=1)}
          <p class="muted">{esc(candles_summary.get("price_basis", ""))} · buckets are {esc(candles_summary.get("bucket_alignment", ""))}</p>
        </section>
        """

    return candles_html


def flow_section(data: dict[str, Any]) -> str:
    flow = data.get("flow")
    flow_summary = (flow or {}).get("summary") or {}
    flow_series = (flow or {}).get("series") or []
    flow_html = ""
    if flow:
        buyer_rows = [
            [
                short(row["wallet"]),
                fmt_eth(row.get("net_flow_eth")),
                fmt_eth(row.get("buy_volume_eth")),
                fmt_eth(row.get("sell_volume_eth")),
                row.get("trades", 0),
            ]
            for row in (flow_summary.get("top_buyers") or [])[:10]
        ]
        seller_rows = [
            [
                short(row["wallet"]),
                fmt_eth(row.get("net_flow_eth")),
                fmt_eth(row.get("buy_volume_eth")),
                fmt_eth(row.get("sell_volume_eth")),
                row.get("trades", 0),
            ]
            for row in (flow_summary.get("top_sellers") or [])[:10]
        ]
        flow_html = f"""
        <section>
          <h2>Order flow</h2>
          <p class="muted">{flow_summary.get("trades", 0)} trades ·
          {fmt_eth(flow_summary.get("buy_volume_eth"))} ETH buy /
          {fmt_eth(flow_summary.get("sell_volume_eth"))} ETH sell ·
          net {fmt_eth(flow_summary.get("net_flow_eth"))} ETH ·
          imbalance {flow_summary.get("flow_imbalance_bps") if flow_summary.get("flow_imbalance_bps") is not None else "—"} bps ·
          median trade {fmt_eth(flow_summary.get("median_trade_eth"))} ETH ·
          p90 {fmt_eth(flow_summary.get("p90_trade_eth"))} ETH ·
          top-decile share {flow_summary.get("top_decile_share_bps") if flow_summary.get("top_decile_share_bps") is not None else "—"} bps</p>
          {flow_svg(flow_series)}
          <h3>Top net buyers</h3>
          {table(["Wallet", "Net ETH", "Buy ETH", "Sell ETH", "Trades"], buyer_rows, numeric_from=1)}
          <h3>Top net sellers</h3>
          {table(["Wallet", "Net ETH", "Buy ETH", "Sell ETH", "Trades"], seller_rows, numeric_from=1)}
        </section>
        """

    return flow_html


def holders_section(data: dict[str, Any]) -> str:
    holders = data.get("holders")
    holders_summary = (holders or {}).get("summary") or {}
    holders_series = (holders or {}).get("timeline") or []
    holders_html = ""
    if holders:
        concentration_rows = [
            [
                str(row.get("start_utc", ""))[11:19],
                row.get("holders", 0),
                row.get("new_holders", 0),
                row.get("exited_holders", 0),
                row.get("top1_bps") if row.get("top1_bps") is not None else "—",
                row.get("top10_bps") if row.get("top10_bps") is not None else "—",
                row.get("hhi_bps") if row.get("hhi_bps") is not None else "—",
            ]
            for row in (holders_summary.get("top_by_concentration") or [])[:10]
        ]
        holders_html = f"""
        <section>
          <h2>Holder concentration</h2>
          <p class="muted">{holders_summary.get("buckets", 0)} buckets at
          {holders_summary.get("bucket_seconds", 0)}s ·
          {holders_summary.get("transfers", 0)} transfers ·
          {holders_summary.get("first_holders", 0)} → {holders_summary.get("last_holders", 0)} holders ·
          peak {holders_summary.get("peak_holders", 0)} ·
          last top1 {holders_summary.get("last_top1_bps") if holders_summary.get("last_top1_bps") is not None else "—"} bps ·
          last top10 {holders_summary.get("last_top10_bps") if holders_summary.get("last_top10_bps") is not None else "—"} bps ·
          last HHI {holders_summary.get("last_hhi_bps") if holders_summary.get("last_hhi_bps") is not None else "—"} bps</p>
          {holder_svg(holders_series)}
          <h3>Peak concentration</h3>
          {table(["Time", "Holders", "New", "Exited", "Top1 bps", "Top10 bps", "HHI bps"], concentration_rows, numeric_from=1)}
          <p class="muted">Protocol addresses are excluded from holder metrics; shares use circulating non-protocol supply.</p>
        </section>
        """

    return holders_html
