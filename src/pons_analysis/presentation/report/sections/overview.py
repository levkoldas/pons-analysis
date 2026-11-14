"""Header cards/badges, quality, launch, window, and source sections."""

from typing import Any

from pons_analysis.presentation.report.formatting import (
    badge,
    esc,
    fmt_eth,
    fmt_num,
    short,
    table,
)


def _quality_label(quality: dict[str, Any]) -> str:
    parts = [
        f"{name} {'yes' if scope.get('passed') else 'no'}"
        for name, scope in (
            ("raw", quality.get("raw")),
            ("derived", quality.get("derived")),
        )
        if scope
    ]
    return " · ".join(parts) if parts else "not run"


def quality_section(data: dict[str, Any]) -> str:
    quality = data.get("quality") or {}
    quality_html = ""
    if quality:
        quality_rows = []
        failed_checks = []
        for label, item in (
            ("Raw evidence", quality.get("raw")),
            ("Derived artifacts", quality.get("derived")),
        ):
            if not item:
                continue
            quality_rows.append(
                [
                    label,
                    "pass" if item.get("passed") else "fail",
                    item.get("checks", 0),
                    item.get("failures", 0),
                ]
            )
            failed_checks.extend(item.get("failed_checks") or [])
        quality_html = f"""
        <section>
          <h2>Data quality</h2>
          <p class="muted">Raw evidence and derived artifact checks are reported separately.
          A failure means downstream conclusions from the affected artifacts are not trustworthy.</p>
          {table(["Scope", "Status", "Checks", "Failures"], quality_rows, numeric_from=2)}
          {table(["Failed checks"], [[name] for name in failed_checks]) if failed_checks else ""}
        </section>
        """

    return quality_html


def launch_section(data: dict[str, Any]) -> str:
    launch = data["launch"]
    holder_rows = [
        [
            short(row["wallet"]),
            fmt_num(row.get("tokens")),
            fmt_num(row.get("pct"), 3),
        ]
        for row in launch["top_holders"]
    ]
    launch_route_rows = [
        [
            short(row["route"]),
            row.get("selector", ""),
            row.get("trades", 0),
            row.get("wallets", 0),
            fmt_eth(row.get("volume_eth")),
        ]
        for row in (launch["summary"].get("top_routes") or [])[:10]
    ]
    return f"""\
<section>
  <h2>Launch</h2>
  <p class="muted">{esc((launch["summary"].get("all") or {}).get("trades", 0))} trades ·
  {fmt_eth((launch["summary"].get("all") or {}).get("volume_eth"))} ETH ·
  {launch["summary"].get("holders", 0)} holders ·
  duration {launch["summary"].get("curve_duration_seconds", "—")}s ·
  {launch["summary"].get("trades_per_second") if launch["summary"].get("trades_per_second") is not None else "—"} trades/s ·
  peak {launch["summary"].get("peak_second_trades", 0)} trades in one second ·
  {launch["summary"].get("routes", 0)} routes</p>
  {table(["Wallet", "Tokens", "% supply"], holder_rows)}
  <h3>Launch routes</h3>
  {table(["Route", "Selector", "Trades", "Wallets", "Volume ETH"], launch_route_rows, numeric_from=2)}
</section>"""


def window_section(data: dict[str, Any]) -> str:
    window = data["window"]
    rotation_rows = [
        [
            f"{row['seconds']:.0f}s" if row["seconds"] is not None else "—",
            short(row["source"]),
            short(row["destination"]),
            fmt_num(row.get("tokens")),
            fmt_eth(row.get("volume_eth")),
        ]
        for row in window["top_rotations"]
    ]
    return f"""\
<section>
  <h2>Analysis window</h2>
  <p class="muted">{window["summary"].get("swaps", 0)} swaps ·
  {window["summary"].get("buys", 0)} buys / {window["summary"].get("sells", 0)} sells ·
  {fmt_eth(window["summary"].get("volume_eth"))} ETH ·
  {window["summary"].get("rotation_count", 0)} rotations ·
  {len(window["summary"].get("direct_transfers") or [])} direct transfers</p>
  {table(["After (s)", "Source", "Destination", "Tokens", "Volume ETH"], rotation_rows, numeric_from=3)}
</section>"""


def sources_section(sources: dict[str, dict[str, Any]]) -> str:
    source_rows = [
        [path, f"{meta['bytes']:,}", meta["sha256"][:16] + "…"]
        for path, meta in sorted(sources.items())
    ]
    return f"""\
<section>
  <h2>Sources</h2>
  <p class="muted">Every rendered section is derived from these workspace artifacts.
  No external assets or network requests are used.</p>
  {table(["Path", "Bytes", "SHA-256"], source_rows, numeric_from=1, css_class="sources")}
</section>"""


def cards_and_badges(
    data: dict[str, Any], sources: dict[str, dict[str, Any]]
) -> tuple[str, str]:
    trajectory = data["trajectory"]
    positions = data["positions"]
    cohort = data.get("cohort")
    funding = data.get("funding")
    clusters = data.get("clusters")
    fees = data.get("fees")
    quality = data.get("quality") or {}
    totals = positions["summary"].get("totals") or {}
    performance = positions["summary"].get("performance") or {}
    replay = trajectory["summary"].get("reserve_replay") or {}
    behavior = (clusters or {}).get("behavior") or {}
    fee_totals = (fees or {}).get("totals") or {}
    cards = [
        ("Volume", f"{fmt_eth(trajectory['summary'].get('volume_eth'))} ETH"),
        ("Net PnL", f"{fmt_eth(totals.get('net_quote_eth'))} ETH"),
        (
            "Wallet ROI",
            f"{performance['net_roi_bps']} bps"
            if performance.get("net_roi_bps") is not None
            else "—",
        ),
        (
            "Median hold",
            f"{performance['median_holding_seconds']}s"
            if performance.get("median_holding_seconds") is not None
            else "—",
        ),
        (
            "Terminal holders",
            str(cohort.get("terminal_holders"))
            if cohort and cohort.get("terminal_holders") is not None
            else "—",
        ),
        (
            "Reserve replay",
            "reconciled"
            if replay.get("reconciled") is True
            else "not reconciled"
            if replay.get("reconciled") is False
            else "n/a",
        ),
        (
            "Funding residual",
            f"{fmt_eth(((funding or {}).get('flow') or {}).get('residual_eth'))} ETH"
            if funding
            else "not included",
        ),
        (
            "Clusters",
            str(clusters.get("clusters"))
            if clusters and clusters.get("clusters") is not None
            else "—"
            if clusters
            else "not included",
        ),
        (
            "Round trips",
            str(behavior.get("round_trips"))
            if clusters and behavior.get("round_trips") is not None
            else "—"
            if clusters
            else "not included",
        ),
        (
            "Fees",
            f"{fmt_eth(fee_totals.get('total_fee_eth'))} ETH"
            if fees
            else "not included",
        ),
        (
            "Fee burden",
            (
                f"{fee_totals['fee_burden_bps']} bps"
                if fee_totals.get("fee_burden_bps") is not None
                else "—"
            )
            if fees
            else "not included",
        ),
        (
            "Data checks",
            _quality_label(quality),
        ),
        ("Source artifacts", str(len(sources))),
    ]
    card_html = "".join(
        f'<div class="card"><div class="k">{esc(key)}</div>'
        f'<div class="v">{esc(value)}</div></div>'
        for key, value in cards
    )
    badges = [
        badge(positions["summary"].get("reconciled"), "positions"),
        badge(replay.get("reconciled"), "reserves"),
        badge((cohort or {}).get("reconciled"), "cohort") if cohort else "",
        badge(((funding or {}).get("flow") or {}).get("reconciled"), "funding")
        if funding
        else "",
        badge((quality.get("raw") or {}).get("passed"), "raw evidence")
        if quality.get("raw")
        else "",
        badge((quality.get("derived") or {}).get("passed"), "derived")
        if quality.get("derived")
        else "",
    ]
    badge_html = " ".join(badge for badge in badges if badge)
    return card_html, badge_html
