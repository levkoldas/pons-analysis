"""Inline SVG chart builders for the standalone HTML report."""

import math
from typing import Any

from pons_analysis.presentation.report.formatting import esc, fmt_eth


def price_svg(series: list[dict[str, Any]]) -> str:
    if not series:
        return '<p class="muted">No price series available.</p>'
    width, height = 900, 320
    left, right, top, bottom = 72, 20, 24, 58
    plot_width = width - left - right
    plot_height = height - top - bottom
    prices = [row["price_eth"] for row in series]
    positive = [price for price in prices if price > 0]
    if not positive:
        return '<p class="muted">No positive price series available.</p>'
    low, high = min(positive), max(positive)
    log_low, log_high = math.log10(low), math.log10(high)
    if log_high == log_low:
        log_low -= 0.01
        log_high += 0.01
    volume_max = max((row["quote_amount"] for row in series), default=0.0)
    count = len(series)

    def x(index: int) -> float:
        return left + (plot_width * index / max(count - 1, 1))

    def y(price: float) -> float:
        if price <= 0:
            price = low
        return top + (log_high - math.log10(price)) / (log_high - log_low) * plot_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Price and volume trajectory" class="chart">'
        f"<title>Log price and volume trajectory over {count} sampled trades</title>"
    ]
    for tick in range(4):
        fraction = tick / 3
        grid_y = top + plot_height * fraction
        price = 10 ** (log_high - (log_high - log_low) * fraction)
        parts.append(
            f'<line x1="{left}" y1="{grid_y:.2f}" x2="{width - right}" '
            f'y2="{grid_y:.2f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{grid_y + 4:.2f}" text-anchor="end" '
            f'class="axis">{price:.2e}</text>'
        )
    parts.append(f'<text x="{left}" y="{top - 8}" class="axis">price (log)</text>')
    if volume_max > 0:
        bar_width = max(plot_width / max(count, 1) * 0.65, 1.0)
        for index, row in enumerate(series):
            fraction = math.sqrt(max(row["quote_amount"], 0.0) / volume_max)
            bar_height = fraction * 34
            parts.append(
                f'<rect x="{x(index) - bar_width / 2:.2f}" '
                f'y="{height - bottom - bar_height:.2f}" '
                f'width="{bar_width:.2f}" height="{bar_height:.2f}" '
                'class="volume"/>'
            )
        parts.append(
            f'<text x="{width - right}" y="{height - 10}" text-anchor="end" '
            'class="axis">volume (sqrt scale)</text>'
        )

    groups: list[list[tuple[int, dict[str, Any]]]] = []
    for index, row in enumerate(series):
        if not groups or groups[-1][0][1]["phase"] != row["phase"]:
            groups.append([])
        groups[-1].append((index, row))
    for group in groups:
        phase = group[0][1]["phase"]
        stroke = "var(--curve)" if phase == "curve" else "var(--v4)"
        if len(group) == 1:
            index, row = group[0]
            parts.append(
                f'<circle cx="{x(index):.2f}" cy="{y(row["price_eth"]):.2f}" '
                f'r="2.5" fill="{stroke}"/>'
            )
            continue
        points = " ".join(
            f"{x(index):.2f},{y(row['price_eth']):.2f}" for index, row in group
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{stroke}" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    parts.append(
        f'<text x="{left}" y="{height - 30}" class="axis">{esc(series[0]["utc"][11:16])}</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - 30}" text-anchor="end" '
        f'class="axis">{esc(series[-1]["utc"][11:16])}</text>'
    )
    parts.append(
        f'<text x="{left}" y="{height - 10}" class="legend curve">curve</text>'
        f'<text x="{left + 70}" y="{height - 10}" class="legend v4">v4</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def candle_svg(candles: list[dict[str, Any]]) -> str:
    if not candles:
        return '<p class="muted">No OHLCV candles available.</p>'
    width, height = 900, 340
    left, right, top, bottom = 72, 20, 24, 34
    volume_height = 44
    price_bottom = height - bottom - volume_height
    plot_width = width - left - right
    plot_height = price_bottom - top
    lows = [row["low_price_eth"] for row in candles]
    highs = [row["high_price_eth"] for row in candles]
    positive = [value for value in lows + highs if value > 0]
    if not positive:
        return '<p class="muted">No positive candle prices available.</p>'
    low, high = min(positive), max(positive)
    log_low, log_high = math.log10(low), math.log10(high)
    if log_high == log_low:
        log_low -= 0.01
        log_high += 0.01
    volume_max = max((row["volume_eth"] for row in candles), default=0.0)
    count = len(candles)

    def x(index: int) -> float:
        return left + plot_width * (index + 0.5) / max(count, 1)

    def y(price: float) -> float:
        if price <= 0:
            price = low
        return top + (log_high - math.log10(price)) / (log_high - log_low) * plot_height

    body_width = max(min(plot_width / max(count, 1) * 0.62, 12.0), 1.0)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="OHLCV candles" class="chart">'
        f"<title>Log-price OHLCV candles over {count} buckets</title>"
    ]
    for tick in range(4):
        fraction = tick / 3
        grid_y = top + plot_height * fraction
        price = 10 ** (log_high - (log_high - log_low) * fraction)
        parts.append(
            f'<line x1="{left}" y1="{grid_y:.2f}" x2="{width - right}" '
            f'y2="{grid_y:.2f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{grid_y + 4:.2f}" text-anchor="end" '
            f'class="axis">{price:.2e}</text>'
        )
    parts.append(f'<text x="{left}" y="{top - 8}" class="axis">price (log)</text>')
    if volume_max > 0:
        volume_base = height - bottom
        for index, row in enumerate(candles):
            fraction = math.sqrt(max(row["volume_eth"], 0.0) / volume_max)
            bar_height = fraction * volume_height
            parts.append(
                f'<rect x="{x(index) - body_width / 2:.2f}" '
                f'y="{volume_base - bar_height:.2f}" '
                f'width="{body_width:.2f}" height="{bar_height:.2f}" '
                'class="volume"/>'
            )
    for index, row in enumerate(candles):
        open_price = row["open_price_eth"]
        close_price = row["close_price_eth"]
        high_price = row["high_price_eth"]
        low_price = row["low_price_eth"]
        css = "candle-up" if close_price >= open_price else "candle-down"
        centre = x(index)
        parts.append(
            f'<line x1="{centre:.2f}" y1="{y(high_price):.2f}" '
            f'x2="{centre:.2f}" y2="{y(low_price):.2f}" class="wick {css}"/>'
        )
        top_y = min(y(open_price), y(close_price))
        body_height = max(abs(y(open_price) - y(close_price)), 1.0)
        parts.append(
            f'<rect x="{centre - body_width / 2:.2f}" y="{top_y:.2f}" '
            f'width="{body_width:.2f}" height="{body_height:.2f}" class="{css}"/>'
        )
    parts.append(
        f'<text x="{left}" y="{height - 10}" class="axis">{esc(candles[0]["start_utc"][11:16])}</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - 10}" text-anchor="end" '
        f'class="axis">{esc(candles[-1]["start_utc"][11:16])}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def holder_svg(timeline: list[dict[str, Any]]) -> str:
    if not timeline:
        return '<p class="muted">No holder timeline available.</p>'
    width, height = 900, 280
    left, right, top, bottom = 72, 64, 24, 42
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_holders = max((row["holders"] for row in timeline), default=1)
    max_holders = max(max_holders, 1)
    count = len(timeline)

    def x(index: int) -> float:
        return left + plot_width * index / max(count - 1, 1)

    def y_holders(value: float) -> float:
        return top + plot_height * (1 - value / max_holders)

    def y_share(value: float) -> float:
        return top + plot_height * (1 - value / 10_000)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Holder count and concentration" class="chart">'
        f"<title>Holder count and top-10 concentration over {count} buckets</title>"
    ]
    for tick in range(4):
        fraction = tick / 3
        grid_y = top + plot_height * fraction
        holders = round(max_holders * (1 - fraction))
        share = round(10_000 * (1 - fraction))
        parts.append(
            f'<line x1="{left}" y1="{grid_y:.2f}" x2="{width - right}" '
            f'y2="{grid_y:.2f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{grid_y + 4:.2f}" text-anchor="end" '
            f'class="axis">{holders}</text>'
        )
        parts.append(
            f'<text x="{width - right + 8}" y="{grid_y + 4:.2f}" '
            f'class="axis">{share / 100:.0f}%</text>'
        )
    holder_points = " ".join(
        f"{x(index):.2f},{y_holders(row['holders']):.2f}"
        for index, row in enumerate(timeline)
    )
    share_rows = [
        (index, row)
        for index, row in enumerate(timeline)
        if row.get("top10_bps") is not None
    ]
    share_points = " ".join(
        f"{x(index):.2f},{y_share(row['top10_bps']):.2f}" for index, row in share_rows
    )
    if count == 1:
        parts.append(
            f'<circle cx="{x(0):.2f}" cy="{y_holders(timeline[0]["holders"]):.2f}" '
            'r="2.5" fill="var(--accent)"/>'
        )
    else:
        parts.append(
            f'<polyline points="{holder_points}" fill="none" stroke="var(--accent)" '
            'stroke-width="2" stroke-linejoin="round"/>'
        )
    if share_rows:
        parts.append(
            f'<polyline points="{share_points}" fill="none" stroke="var(--warning)" '
            'stroke-width="2" stroke-linejoin="round" stroke-dasharray="4 3"/>'
        )
    parts.append(
        f'<text x="{left}" y="{height - 10}" class="axis">{esc(timeline[0]["start_utc"][11:16])}</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - 10}" text-anchor="end" '
        f'class="axis">{esc(timeline[-1]["start_utc"][11:16])}</text>'
    )
    parts.append(f'<text x="{left}" y="{top - 8}" class="axis">holders</text>')
    parts.append(
        f'<text x="{width - right}" y="{top - 8}" text-anchor="end" '
        'class="axis">top-10 share</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def flow_svg(series: list[dict[str, Any]]) -> str:
    if not series:
        return '<p class="muted">No order-flow buckets available.</p>'
    width, height = 900, 260
    left, right, top, bottom = 72, 20, 24, 40
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_abs = max((abs(row["net_flow_eth"]) for row in series), default=0.0)
    if max_abs == 0:
        max_abs = 1.0
    count = len(series)

    def x(index: int) -> float:
        return left + plot_width * (index + 0.5) / max(count, 1)

    def y(value: float) -> float:
        return top + plot_height * (0.5 - value / (2 * max_abs))

    bar_width = max(plot_width / max(count, 1) * 0.66, 1.0)
    mid = top + plot_height / 2
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Bucket net order flow" class="chart">'
        f"<title>Net buy-minus-sell flow over {count} buckets</title>"
    ]
    for tick in range(3):
        value = max_abs * (1 - tick)
        grid_y = y(value)
        parts.append(
            f'<line x1="{left}" y1="{grid_y:.2f}" x2="{width - right}" '
            f'y2="{grid_y:.2f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{left - 8}" y="{grid_y + 4:.2f}" text-anchor="end" '
            f'class="axis">{value:,.4f}</text>'
        )
    parts.append(
        f'<line x1="{left}" y1="{mid:.2f}" x2="{width - right}" '
        f'y2="{mid:.2f}" class="grid"/>'
    )
    for index, row in enumerate(series):
        value = row["net_flow_eth"]
        top_y = min(y(value), y(0.0))
        bar_height = abs(y(value) - y(0.0))
        css = "candle-up" if value >= 0 else "candle-down"
        parts.append(
            f'<rect x="{x(index) - bar_width / 2:.2f}" y="{top_y:.2f}" '
            f'width="{bar_width:.2f}" height="{bar_height:.2f}" class="{css}"/>'
        )
    parts.append(
        f'<text x="{left}" y="{height - 10}" class="axis">{esc(series[0]["start_utc"][11:16])}</text>'
    )
    parts.append(
        f'<text x="{width - right}" y="{height - 10}" text-anchor="end" '
        f'class="axis">{esc(series[-1]["start_utc"][11:16])}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def pnl_histogram_svg(histogram: list[dict[str, Any]]) -> str:
    if not histogram:
        return '<p class="muted">No wallet PnL histogram available.</p>'
    width, height = 900, 220
    left, right, top, bottom = 70, 20, 24, 42
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_count = max((row["count"] for row in histogram), default=1)
    max_count = max(max_count, 1)
    low = histogram[0]["lower_net_eth"]
    high = histogram[-1]["upper_net_eth"]
    bar_width = plot_width / len(histogram)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Wallet net PnL histogram" class="chart">'
        f"<title>Wallet net PnL distribution over {len(histogram)} bins</title>"
    ]
    parts.append(
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" class="grid"/>'
    )
    parts.append(
        f'<text x="{left - 8}" y="{top + 4}" text-anchor="end" class="axis">'
        f"{max_count}</text>"
    )
    parts.append(
        f'<text x="{left - 8}" y="{height - bottom + 4}" text-anchor="end" '
        'class="axis">0</text>'
    )
    for index, row in enumerate(histogram):
        bar_height = plot_height * row["count"] / max_count
        x0 = left + index * bar_width
        parts.append(
            f'<rect x="{x0:.2f}" y="{height - bottom - bar_height:.2f}" '
            f'width="{max(bar_width - 1, 1):.2f}" height="{bar_height:.2f}" '
            'fill="var(--accent)" opacity="0.8">'
            f"<title>{fmt_eth(row['lower_net_eth'])} to "
            f"{fmt_eth(row['upper_net_eth'])} ETH: {row['count']} wallets</title>"
            "</rect>"
        )
    if low is not None and high is not None and low < 0 < high:
        zero_x = left + plot_width * (-low) / (high - low)
        parts.append(
            f'<line x1="{zero_x:.2f}" y1="{top}" x2="{zero_x:.2f}" '
            f'y2="{height - bottom}" class="grid"/>'
        )
        parts.append(
            f'<text x="{zero_x:.2f}" y="{height - 10}" text-anchor="middle" '
            'class="axis">0 ETH</text>'
        )
    if low is not None:
        parts.append(
            f'<text x="{left}" y="{height - 10}" class="axis">{fmt_eth(low)}</text>'
        )
    if high is not None:
        parts.append(
            f'<text x="{width - right}" y="{height - 10}" text-anchor="end" '
            f'class="axis">{fmt_eth(high)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
