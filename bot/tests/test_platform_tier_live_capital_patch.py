from __future__ import annotations

from bot import platform_tier_live_capital_patch as patch


class FakeTierConfigModule:
    __name__ = "bot.tier_config"

    @staticmethod
    def get_tier_from_balance(balance, override_tier=None, is_platform=False):
        return (balance, override_tier, is_platform)

    @staticmethod
    def validate_trade_size(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return (True, f"balance={balance:.2f} trade={trade_size:.2f} exchange={exchange}")

    @staticmethod
    def auto_resize_trade(trade_size, tier, balance, is_platform=False, exchange="coinbase"):
        return (trade_size, f"balance={balance:.2f} exchange={exchange}")


def test_effective_balance_uses_live_platform_capital(monkeypatch):
    monkeypatch.setattr(patch, "_live_platform_capital", lambda: 580.35)
    effective, changed, live = patch._effective_balance(116.09, is_platform=True)

    assert changed is True
    assert live == 580.35
    assert effective == 580.35


def test_effective_balance_keeps_large_local_balance(monkeypatch):
    monkeypatch.setattr(patch, "_live_platform_capital", lambda: 580.35)
    effective, changed, live = patch._effective_balance(700.00, is_platform=True)

    assert changed is False
    assert live == 580.35
    assert effective == 700.00


def test_patch_tier_config_validate_trade_size_uses_live_capital(monkeypatch):
    monkeypatch.setattr(patch, "_live_platform_capital", lambda: 580.35)
    module = FakeTierConfigModule()

    assert patch._patch_tier_config(module) is True
    ok, reason = module.validate_trade_size(35.25, "INVESTOR", 116.09, is_platform=True, exchange="kraken")

    assert ok is True
    assert "balance=580.35" in reason
