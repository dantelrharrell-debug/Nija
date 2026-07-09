from __future__ import annotations

from types import SimpleNamespace

from bot import kraken_tier_floor_platform_capital_repair_patch as patch


class FakeTier:
    value = "SAVER"


class FakeCapitalAuthority:
    def get_real_capital(self):
        return 579.50


def test_kraken_tier_floor_repair_allows_exchange_floor_when_platform_capital_ready(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_NOTIONAL_USD", "23")
    monkeypatch.setenv("NIJA_PLATFORM_TOTAL_CAPITAL_USD", "579.50")
    module = SimpleNamespace(__name__="bot.tier_config")

    def validate_trade_size(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return False, "Trade size $28.98 below tier minimum $250.00"

    module.validate_trade_size = validate_trade_size
    assert patch._patch_tier_config(module) is True

    ok, reason = module.validate_trade_size(28.98, FakeTier(), 116.09, is_platform=False, exchange="kraken")

    assert ok is True
    assert "kraken platform-capital" in reason


def test_kraken_tier_floor_repair_refuses_below_exchange_floor(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_NOTIONAL_USD", "23")
    monkeypatch.setenv("NIJA_PLATFORM_TOTAL_CAPITAL_USD", "579.50")
    module = SimpleNamespace(__name__="bot.tier_config")

    def validate_trade_size(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return False, "Trade size $10.00 below tier minimum $250.00"

    module.validate_trade_size = validate_trade_size
    assert patch._patch_tier_config(module) is True

    ok, reason = module.validate_trade_size(10.0, FakeTier(), 116.09, is_platform=False, exchange="kraken")

    assert ok is False
    assert "below tier minimum" in reason


def test_kraken_tier_floor_repair_refuses_when_platform_capital_not_ready(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_NOTIONAL_USD", "23")
    monkeypatch.setenv("NIJA_PLATFORM_TOTAL_CAPITAL_USD", "200.00")
    module = SimpleNamespace(__name__="bot.tier_config")

    def validate_trade_size(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return False, "Trade size $28.98 below tier minimum $250.00"

    module.validate_trade_size = validate_trade_size
    assert patch._patch_tier_config(module) is True

    ok, reason = module.validate_trade_size(28.98, FakeTier(), 116.09, is_platform=False, exchange="kraken")

    assert ok is False
    assert "below tier minimum" in reason


def test_kraken_resize_repair_returns_original_size_when_valid(monkeypatch):
    monkeypatch.setenv("KRAKEN_MIN_NOTIONAL_USD", "23")
    monkeypatch.setenv("NIJA_PLATFORM_TOTAL_CAPITAL_USD", "579.50")
    module = SimpleNamespace(__name__="bot.tier_config")

    def auto_resize_trade(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return 0.0, "Trade $28.98 below minimum $250.00 (cannot resize up)"

    module.auto_resize_trade = auto_resize_trade
    assert patch._patch_tier_config(module) is True

    size, reason = module.auto_resize_trade(28.98, FakeTier(), 116.09, is_platform=False, exchange="kraken")

    assert size == 28.98
    assert "kraken platform-capital" in reason
