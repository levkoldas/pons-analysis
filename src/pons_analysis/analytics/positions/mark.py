"""Mark-price extraction and market-value arithmetic."""

from typing import Any

from pons_analysis.analytics.common.artifacts import utc
from pons_analysis.core.accounting.amm import Q96
from pons_analysis.core.errors import InvariantError
from pons_analysis.core.evm import sig, words
from pons_analysis.core.models import Launch, RpcLog

CURVE_BUY_TOPIC = sig("CurveBuy(address,address,uint256,uint256,uint256,uint256)")
CURVE_SELL_TOPIC = sig("CurveSell(address,address,uint256,uint256,uint256,uint256)")


def _curve_mark(
    curve_logs: list[RpcLog], timestamps: dict[int, int], profile: Launch
) -> dict[str, Any] | None:
    """Last observed curve execution price, for launches that have not migrated."""

    for log in reversed(curve_logs):
        if not log.topics or log.topics[0] not in (CURVE_BUY_TOPIC, CURVE_SELL_TOPIC):
            continue
        values = words(log)
        if len(values) < 4:
            raise InvariantError("Curve trade event is shorter than four words")
        if log.topics[0] == CURVE_BUY_TOPIC:
            quote_raw, token_raw = values[0], values[1]
        else:
            token_raw, quote_raw = values[0], values[1]
        if quote_raw <= 0 or token_raw <= 0:
            continue
        timestamp = timestamps.get(log.block_number)
        return {
            "source": "curve",
            "block": log.block_number,
            "timestamp": timestamp,
            "utc": utc(timestamp) if timestamp is not None else None,
            "price_raw_per_token": quote_raw / token_raw,
            "price_eth_per_token": (quote_raw / 1e18)
            / (token_raw / 10**profile.decimals),
            "quote_raw": quote_raw,
            "token_raw": token_raw,
        }
    return None


def _mark_price(
    swaps: list[RpcLog],
    timestamps: dict[int, int],
    profile: Launch,
    curve_logs: list[RpcLog] | None = None,
) -> dict[str, Any] | None:
    if not swaps:
        return _curve_mark(curve_logs or [], timestamps, profile)
    last = swaps[-1]
    values = words(last)
    sqrt_price = values[2]
    if sqrt_price <= 0:
        raise InvariantError("V4 mark price must be positive")
    price_raw = (Q96 / sqrt_price) ** 2
    timestamp = timestamps.get(last.block_number)
    return {
        "source": "v4",
        "sqrt_price_x96": sqrt_price,
        "block": last.block_number,
        "timestamp": timestamp,
        "utc": utc(timestamp) if timestamp is not None else None,
        "price_raw_per_token": price_raw,
        "price_eth_per_token": price_raw * 10**profile.decimals / 10**18,
    }


def _mark_value(tokens: int, mark: dict[str, Any] | None) -> int | None:
    if tokens == 0:
        return 0
    if mark is None:
        return None
    if "quote_raw" in mark:
        return tokens * mark["quote_raw"] // mark["token_raw"]
    sqrt_price = mark["sqrt_price_x96"]
    return tokens * Q96 * Q96 // (sqrt_price * sqrt_price)
