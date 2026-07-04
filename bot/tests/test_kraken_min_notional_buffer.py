import pytest

from bot.exchange_order_compiler import ExchangeOrderCompiler, PricingSnapshot
from bot.kraken_order_validator import (
    get_pair_safe_minimums,
    validate_and_adjust_order,
    validate_order_size,
)


def test_kraken_buy_at_raw_minimum_is_lifted_above_buffer(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03")
    monkeypatch.setenv("KRAKEN_BUY_BUFFER_PCT", "0.004")

    price = 0.5987
    raw_volume_for_twenty_dollars = 20.00 / price

    # The raw $20.00 order should no longer pass because Kraken validation now
    # requires buffered post-conversion notional instead of exact-min notional.
    is_valid_raw, raw_error = validate_order_size(
        "AEROUSD",
        raw_volume_for_twenty_dollars,
        price,
        "buy",
    )
    assert is_valid_raw is False
    assert "safe minimum" in str(raw_error)

    is_valid, adjusted_volume, error = validate_and_adjust_order(
        pair="AEROUSD",
        volume=raw_volume_for_twenty_dollars,
        price=price,
        side="buy",
        ordertype="market",
    )

    safe_minimums = get_pair_safe_minimums("AEROUSD")
    assert is_valid is True
    assert error is None
    assert adjusted_volume * price >= pytest.approx(safe_minimums["min_quote"], rel=0, abs=0.001)
    assert adjusted_volume > raw_volume_for_twenty_dollars


def test_eoc_kraken_compile_uses_buffered_post_rounding_minimum(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03")

    compiler = ExchangeOrderCompiler()
    pricing = PricingSnapshot(
        symbol="AERO-USD",
        bid=0.5986,
        ask=0.5987,
        mid=0.59865,
        available_balance_usd=130.00,
    )

    order = compiler.compile(
        symbol="AERO-USD",
        side="buy",
        size_usd=20.00,
        pricing=pricing,
        exchange="kraken",
    )

    assert order.size_usd >= 20.60
    assert order.quantity * order.price >= pytest.approx(20.60, rel=0, abs=0.001)
    assert order.is_exchange_valid is True
