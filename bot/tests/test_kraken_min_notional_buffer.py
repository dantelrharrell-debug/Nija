from bot.exchange_order_compiler import ExchangeOrderCompiler, PricingSnapshot
from bot.kraken_order_validator import (
    get_pair_safe_minimums,
    validate_and_adjust_order,
    validate_order_size,
)


def test_floor_sized_kraken_quote_is_lifted_with_buffer(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03")
    monkeypatch.setenv("KRAKEN_BUY_BUFFER_PCT", "0.004")

    price = 0.5987
    raw_volume = 20.00 / price

    valid_before, raw_error = validate_order_size("AEROUSD", raw_volume, price, "buy")
    assert valid_before is False
    assert "safe minimum" in str(raw_error)

    valid_after, adjusted_volume, error = validate_and_adjust_order(
        pair="AEROUSD",
        volume=raw_volume,
        price=price,
        side="buy",
        ordertype="market",
    )

    safe_minimums = get_pair_safe_minimums("AEROUSD")
    assert valid_after is True
    assert error is None
    assert adjusted_volume * price >= safe_minimums["min_quote"] - 0.001
    assert adjusted_volume > raw_volume


def test_eoc_lifts_kraken_quote_to_buffered_floor(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03")

    compiler = ExchangeOrderCompiler()
    pricing = PricingSnapshot(
        symbol="AERO-USD",
        bid=0.5986,
        ask=0.5987,
        mid=0.59865,
        available_balance_usd=130.00,
    )

    compiled = compiler.compile(
        symbol="AERO-USD",
        side="buy",
        size_usd=20.00,
        pricing=pricing,
        exchange="kraken",
    )

    assert compiled.size_usd >= 20.60
    assert compiled.quantity * compiled.price >= 20.60 - 0.001
    assert compiled.is_exchange_valid is True
