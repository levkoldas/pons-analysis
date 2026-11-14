"""Constant-product and Uniswap-v4 pricing identities.

Reserve arithmetic stays integer wei where the formula allows it; only the
human-facing price ratio is a float. Formulas are the standard ``x*y = k``
results, so they apply to any curve or pool that exposes reserves.
"""

Q96 = 2**96


def v4_price(sqrt_price_x96: int) -> float:
    """Quote per base token for a Q96 sqrt price."""
    if sqrt_price_x96 <= 0:
        raise ValueError("sqrtPriceX96 must be positive")
    return (Q96 / sqrt_price_x96) ** 2


def v4_price_eth(sqrt_price_x96: int, token_decimals: int) -> float:
    """Quote per whole base token in native quote units (e.g. ETH)."""
    return v4_price(sqrt_price_x96) * 10**token_decimals / 10**18


def v4_virtual_reserves(liquidity: int, sqrt_price_x96: int) -> tuple[int, int]:
    """Return ``(quote_reserve, token_reserve)`` implied by ``L`` and sqrt price."""
    if liquidity < 0 or sqrt_price_x96 <= 0:
        raise ValueError("Liquidity and sqrtPriceX96 must be non-negative")
    return liquidity * Q96 // sqrt_price_x96, liquidity * sqrt_price_x96 // Q96


def reserve_exit_gross(tokens: int, quote_reserve: int, token_reserve: int) -> int:
    """Quote received by selling ``tokens`` into a constant-product reserve."""
    if tokens < 0 or quote_reserve < 0 or token_reserve < 0:
        raise ValueError("Reserves and token amounts must be non-negative")
    if tokens + token_reserve == 0:
        raise ValueError("Sale leaves no token reserve")
    return tokens * quote_reserve // (token_reserve + tokens)


def net_after_fees(gross: int, *fee_bps: int) -> int:
    """Subtract each basis-point fee from the gross amount, truncating each."""
    fees = 0
    total_bps = 0
    for bps in fee_bps:
        if not 0 <= bps <= 10_000:
            raise ValueError("Fee must be within 0..10000 basis points")
        total_bps += bps
        if total_bps > 10_000:
            raise ValueError("Combined fees must not exceed 10000 basis points")
        fees += gross * bps // 10_000
    return gross - fees
