"""Assemble the deterministic standalone HTML report document."""

from typing import Any

from pons_analysis.core.constants import REPORT_SCHEMA_VERSION as SCHEMA_VERSION
from pons_analysis.presentation.report.formatting import decorate_sections, esc, short
from pons_analysis.presentation.report.sections.evidence import (
    cluster_quality_section,
    clusters_section,
    execution_section,
    fees_section,
    funding_section,
    provenance_section,
    route_performance_section,
)
from pons_analysis.presentation.report.sections.market import (
    candles_section,
    flow_section,
    holders_section,
    trajectory_section,
)
from pons_analysis.presentation.report.sections.overview import (
    cards_and_badges,
    launch_section,
    quality_section,
    sources_section,
    window_section,
)
from pons_analysis.presentation.report.sections.wallets import (
    cohort_section,
    entry_cohorts_section,
    lifecycle_section,
    retention_section,
    wallet_pnl_section,
    wallet_scorecard_section,
)
from pons_analysis.presentation.report.styles import STYLES


def render_html(data: dict[str, Any], sources: dict[str, dict[str, Any]]) -> bytes:
    """Render the report data into one self-contained HTML document."""
    profile = data["profile"]
    card_html, badge_html = cards_and_badges(data, sources)
    quality_html = quality_section(data)
    trajectory_html = trajectory_section(data)
    candles_html = candles_section(data)
    flow_html = flow_section(data)
    holders_html = holders_section(data)
    wallet_scorecard_html = wallet_scorecard_section(data)
    entry_cohorts_html = entry_cohorts_section(data)
    retention_html = retention_section(data)
    wallet_pnl_html = wallet_pnl_section(data)
    launch_html = launch_section(data)
    route_performance_html = route_performance_section(data)
    window_html = window_section(data)
    cohort_html = cohort_section(data)
    lifecycle_html = lifecycle_section(data)
    execution_html = execution_section(data)
    cluster_quality_html = cluster_quality_section(data)
    clusters_html = clusters_section(data)
    fees_html = fees_section(data)
    funding_html = funding_section(data)
    provenance_html = provenance_section(data)
    sources_html = sources_section(sources)
    return decorate_sections(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src 'none'; script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>{esc(profile["name"])} · {short(profile["token"])} report</title>
<style>
{STYLES}
</style>
</head>
<body id="top">
<main>
<header>
  <div class="muted">{esc(profile["chain"])} · {esc(data["minutes"])} minute window</div>
  <h1>{esc(profile["name"])} · <code>{short(profile["token"])}</code></h1>
  <div class="muted">{esc(data["period"]["start_utc"])} → {esc(data["period"]["end_utc"])}</div>
  <div style="margin-top:12px">{badge_html}</div>
</header>
<div class="cards">{card_html}</div>
<!--TOC-->

{quality_html}

{trajectory_html}

{candles_html}
{flow_html}
{holders_html}
{wallet_scorecard_html}
{entry_cohorts_html}
{retention_html}

{wallet_pnl_html}

{launch_html}

{route_performance_html}

{window_html}

{cohort_html}
{lifecycle_html}
{execution_html}
{cluster_quality_html}
{clusters_html}
{fees_html}
{funding_html}
{provenance_html}

{sources_html}
</main>
<footer>pons-analysis · deterministic file-based report · schema {SCHEMA_VERSION}</footer>
</body>
</html>
"""
    ).encode("utf-8")
