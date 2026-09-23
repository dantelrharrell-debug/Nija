import math

import pytest

from bot.options_analytics import (
    analyze_option,
    black_scholes_greeks,
    black_scholes_price,
    implied_volatility,
    no_arbitrage_bounds,
)


def test_black_scholes_reference_prices() -> None:
    call = black_scholes_price(100.0, 100.0, 1.0, 0.05, 0.20, "call")
    put = black_scholes_price(100.0, 100.0, 1.0, 0.05, 0.20, "put")

    assert call == pytest.approx(10.4505835722, rel=1e-9)
    assert put == pytest.approx(5.5735260223, rel=1e-9)


def test_put_call_parity_without_dividends() -> None:
    spot = 100.0
    strike = 100.0
    time_to_expiry = 1.0
    rate = 0.05
    vol = 0.20

    call = black_scholes_price(spot, strike, time_to_expiry, rate, vol, "call")
    put = black_scholes_price(spot, strike, time_to_expiry, rate, vol, "put")

    parity_rhs = spot - strike * math.exp(-rate * time_to_expiry)
    assert call - put == pytest.approx(parity_rhs, rel=1e-10)


def test_greeks_reference_values_and_signs() -> None:
    greeks = black_scholes_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "call")

    assert greeks.delta == pytest.approx(0.6368306512, rel=1e-9)
    assert greeks.gamma == pytest.approx(0.01876201735, rel=1e-9)
    assert greeks.theta < 0.0
    assert greeks.vega > 0.0
    assert greeks.rho > 0.0


def test_implied_volatility_round_trip() -> None:
    market_price = black_scholes_price(100.0, 100.0, 1.0, 0.05, 0.20, "call")
    solved = implied_volatility(
        market_price=market_price,
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        option_type="call",
    )

    assert solved == pytest.approx(0.20, abs=1e-6)


def test_analyze_option_reports_model_edge_and_implied_volatility() -> None:
    result = analyze_option(
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        option_type="call",
        volatility=0.20,
        market_price=11.0,
    )

    assert result.theoretical_price == pytest.approx(10.4505835722, rel=1e-9)
    assert result.model_edge_abs is not None
    assert result.model_edge_abs > 0.0
    assert result.implied_volatility is not None


def test_expired_option_returns_intrinsic_value() -> None:
    assert black_scholes_price(110.0, 100.0, 0.0, 0.05, 0.20, "call") == 10.0
    assert black_scholes_price(90.0, 100.0, 0.0, 0.05, 0.20, "put") == 10.0


def test_implied_volatility_rejects_price_outside_bounds() -> None:
    lower, upper = no_arbitrage_bounds(100.0, 100.0, 1.0, 0.05, "call")
    assert lower >= 0.0
    assert upper == pytest.approx(100.0)

    with pytest.raises(ValueError, match="outside no-arbitrage bounds"):
        implied_volatility(
            market_price=120.0,
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.05,
            option_type="call",
        )
