"""
NIJA Black-Scholes-Merton Options Analytics
===========================================

Pure, dependency-free analytics for European-style vanilla options.

This module is intentionally analytics-only. It does not authorize orders,
change risk parameters, size positions, or bypass any NIJA execution/risk gate.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class OptionGreeks:
    """Black-Scholes-Merton Greeks using annualized inputs."""

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float

    def to_dict(self) -> Dict[str, float]:
        """Return the Greeks as a plain dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class OptionAnalytics:
    """Structured Black-Scholes-Merton valuation result."""

    option_type: str
    spot: float
    strike: float
    time_to_expiry_years: float
    risk_free_rate: float
    dividend_yield: float
    volatility: float
    theoretical_price: float
    intrinsic_value: float
    time_value: float
    greeks: OptionGreeks
    market_price: Optional[float] = None
    implied_volatility: Optional[float] = None
    model_edge_abs: Optional[float] = None
    model_edge_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-friendly representation."""
        return asdict(self)


def _normalize_option_type(option_type: str) -> str:
    value = str(option_type).strip().lower()
    if value in {"c", "call"}:
        return "call"
    if value in {"p", "put"}:
        return "put"
    raise ValueError("option_type must be 'call' or 'put'")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _validate_positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _validate_non_negative(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def intrinsic_value(spot: float, strike: float, option_type: str) -> float:
    """Return intrinsic value for a call or put."""
    spot = _validate_positive("spot", spot)
    strike = _validate_positive("strike", strike)
    option_type = _normalize_option_type(option_type)
    return max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)


def _d1_d2(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    dividend_yield: float,
) -> tuple[float, float]:
    sqrt_t = math.sqrt(time_to_expiry_years)
    denom = volatility * sqrt_t
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility)
        * time_to_expiry_years
    ) / denom
    d2 = d1 - denom
    return d1, d2


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> float:
    """
    Price a European vanilla option with the Black-Scholes-Merton model.

    Rates and volatility are decimals (5% => 0.05, 20% => 0.20).
    """
    spot = _validate_positive("spot", spot)
    strike = _validate_positive("strike", strike)
    time_to_expiry_years = _validate_non_negative(
        "time_to_expiry_years", time_to_expiry_years
    )
    volatility = _validate_non_negative("volatility", volatility)
    risk_free_rate = float(risk_free_rate)
    dividend_yield = float(dividend_yield)
    option_type = _normalize_option_type(option_type)

    if not math.isfinite(risk_free_rate) or not math.isfinite(dividend_yield):
        raise ValueError("rates must be finite numbers")

    if time_to_expiry_years == 0.0 or volatility == 0.0:
        forward_spot = spot * math.exp(
            (risk_free_rate - dividend_yield) * time_to_expiry_years
        )
        discounted_payoff = intrinsic_value(forward_spot, strike, option_type)
        return discounted_payoff * math.exp(-risk_free_rate * time_to_expiry_years)

    d1, d2 = _d1_d2(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
        dividend_yield,
    )
    discounted_spot = spot * math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)

    if option_type == "call":
        return discounted_spot * _norm_cdf(d1) - discounted_strike * _norm_cdf(d2)

    return discounted_strike * _norm_cdf(-d2) - discounted_spot * _norm_cdf(-d1)


def black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> OptionGreeks:
    """
    Calculate Black-Scholes-Merton Delta, Gamma, Theta, Vega, and Rho.

    Theta is annual price decay. Vega and Rho are per 1.00 change in volatility
    and rates respectively; divide by 100 for a one-percentage-point sensitivity.
    """
    spot = _validate_positive("spot", spot)
    strike = _validate_positive("strike", strike)
    time_to_expiry_years = _validate_non_negative(
        "time_to_expiry_years", time_to_expiry_years
    )
    volatility = _validate_non_negative("volatility", volatility)
    risk_free_rate = float(risk_free_rate)
    dividend_yield = float(dividend_yield)
    option_type = _normalize_option_type(option_type)

    if time_to_expiry_years == 0.0 or volatility == 0.0:
        if option_type == "call":
            delta = 1.0 if spot > strike else 0.0 if spot < strike else 0.5
        else:
            delta = -1.0 if spot < strike else 0.0 if spot > strike else -0.5
        return OptionGreeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

    d1, d2 = _d1_d2(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
        dividend_yield,
    )
    sqrt_t = math.sqrt(time_to_expiry_years)
    discounted_spot_factor = math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    pdf_d1 = _norm_pdf(d1)

    gamma = discounted_spot_factor * pdf_d1 / (spot * volatility * sqrt_t)
    vega = spot * discounted_spot_factor * pdf_d1 * sqrt_t
    common_theta = (
        -spot
        * discounted_spot_factor
        * pdf_d1
        * volatility
        / (2.0 * sqrt_t)
    )

    if option_type == "call":
        delta = discounted_spot_factor * _norm_cdf(d1)
        theta = (
            common_theta
            - risk_free_rate * discounted_strike * _norm_cdf(d2)
            + dividend_yield
            * spot
            * discounted_spot_factor
            * _norm_cdf(d1)
        )
        rho = (
            strike
            * time_to_expiry_years
            * math.exp(-risk_free_rate * time_to_expiry_years)
            * _norm_cdf(d2)
        )
    else:
        delta = discounted_spot_factor * (_norm_cdf(d1) - 1.0)
        theta = (
            common_theta
            + risk_free_rate * discounted_strike * _norm_cdf(-d2)
            - dividend_yield
            * spot
            * discounted_spot_factor
            * _norm_cdf(-d1)
        )
        rho = (
            -strike
            * time_to_expiry_years
            * math.exp(-risk_free_rate * time_to_expiry_years)
            * _norm_cdf(-d2)
        )

    return OptionGreeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def no_arbitrage_bounds(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> tuple[float, float]:
    """Return European option no-arbitrage lower and upper price bounds."""
    spot = _validate_positive("spot", spot)
    strike = _validate_positive("strike", strike)
    time_to_expiry_years = _validate_non_negative(
        "time_to_expiry_years", time_to_expiry_years
    )
    risk_free_rate = float(risk_free_rate)
    dividend_yield = float(dividend_yield)
    option_type = _normalize_option_type(option_type)

    discounted_spot = spot * math.exp(-dividend_yield * time_to_expiry_years)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)

    if option_type == "call":
        return max(0.0, discounted_spot - discounted_strike), discounted_spot
    return max(0.0, discounted_strike - discounted_spot), discounted_strike


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
    min_volatility: float = 1e-6,
    max_volatility: float = 5.0,
    tolerance: float = 1e-8,
    max_iterations: int = 200,
) -> float:
    """
    Solve for implied volatility using a robust bisection search.

    Raises ValueError when the market price violates European no-arbitrage bounds.
    """
    market_price = _validate_non_negative("market_price", market_price)
    time_to_expiry_years = _validate_positive(
        "time_to_expiry_years", time_to_expiry_years
    )
    option_type = _normalize_option_type(option_type)
    min_volatility = _validate_positive("min_volatility", min_volatility)
    max_volatility = _validate_positive("max_volatility", max_volatility)
    tolerance = _validate_positive("tolerance", tolerance)

    if min_volatility >= max_volatility:
        raise ValueError("min_volatility must be less than max_volatility")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")

    lower_bound, upper_bound = no_arbitrage_bounds(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        option_type,
        dividend_yield,
    )
    eps = max(tolerance, 1e-12)
    if market_price < lower_bound - eps or market_price > upper_bound + eps:
        raise ValueError(
            f"market_price {market_price} is outside no-arbitrage bounds "
            f"[{lower_bound}, {upper_bound}]"
        )

    low = min_volatility
    high = max_volatility
    low_price = black_scholes_price(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        low,
        option_type,
        dividend_yield,
    )
    high_price = black_scholes_price(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        high,
        option_type,
        dividend_yield,
    )

    if market_price <= low_price + tolerance:
        return low
    if market_price >= high_price - tolerance:
        return high

    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        model_price = black_scholes_price(
            spot,
            strike,
            time_to_expiry_years,
            risk_free_rate,
            mid,
            option_type,
            dividend_yield,
        )
        diff = model_price - market_price
        if abs(diff) <= tolerance:
            return mid
        if diff > 0.0:
            high = mid
        else:
            low = mid

    return 0.5 * (low + high)


def analyze_option(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str = "call",
    volatility: Optional[float] = None,
    market_price: Optional[float] = None,
    dividend_yield: float = 0.0,
) -> OptionAnalytics:
    """
    Produce a complete valuation/Greeks snapshot.

    If volatility is omitted, market_price is required and implied volatility is
    solved first. A positive model_edge_abs means market price is above model value.
    """
    option_type = _normalize_option_type(option_type)

    solved_iv: Optional[float] = None
    if volatility is None:
        if market_price is None:
            raise ValueError("volatility or market_price is required")
        solved_iv = implied_volatility(
            market_price=market_price,
            spot=spot,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate,
            option_type=option_type,
            dividend_yield=dividend_yield,
        )
        volatility = solved_iv
    else:
        volatility = _validate_non_negative("volatility", volatility)
        if market_price is not None and time_to_expiry_years > 0.0:
            try:
                solved_iv = implied_volatility(
                    market_price=market_price,
                    spot=spot,
                    strike=strike,
                    time_to_expiry_years=time_to_expiry_years,
                    risk_free_rate=risk_free_rate,
                    option_type=option_type,
                    dividend_yield=dividend_yield,
                )
            except ValueError:
                solved_iv = None

    theoretical = black_scholes_price(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
        option_type=option_type,
        dividend_yield=dividend_yield,
    )
    greeks = black_scholes_greeks(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        volatility=volatility,
        option_type=option_type,
        dividend_yield=dividend_yield,
    )
    intrinsic = intrinsic_value(spot, strike, option_type)
    market = float(market_price) if market_price is not None else None
    edge_abs = None if market is None else market - theoretical
    edge_pct = None if edge_abs is None or theoretical == 0.0 else edge_abs / theoretical

    return OptionAnalytics(
        option_type=option_type,
        spot=float(spot),
        strike=float(strike),
        time_to_expiry_years=float(time_to_expiry_years),
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
        volatility=float(volatility),
        theoretical_price=theoretical,
        intrinsic_value=intrinsic,
        time_value=max(0.0, theoretical - intrinsic),
        greeks=greeks,
        market_price=market,
        implied_volatility=solved_iv,
        model_edge_abs=edge_abs,
        model_edge_pct=edge_pct,
    )


__all__ = [
    "OptionAnalytics",
    "OptionGreeks",
    "analyze_option",
    "black_scholes_greeks",
    "black_scholes_price",
    "implied_volatility",
    "intrinsic_value",
    "no_arbitrage_bounds",
]
