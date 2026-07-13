from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import profit_first_loss_prevention_patch as pf


def live_env(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_PROFIT_FIRST_ALLOW_UNSAFE_OVERRIDES", "false")
    monkeypatch.setenv("NIJA_ALLOW_LIVE_FREQUENCY_RELAXATION", "false")
    monkeypatch.setenv("NIJA_LIVE_FALLBACK_ENTRY_ALLOWED", "false")


def test_safe_stop_geometry_preserves_dollar_risk(monkeypatch):
    live_env(monkeypatch)
    monkeypatch.setenv("NIJA_PROFIT_FIRST_MIN_STOP_PCT", "0.015")
    monkeypatch.setenv("NIJA_PROFIT_FIRST_MAX_STOP_PCT", "0.025")
    size, stop, old_pct, new_pct = pf._safe_stop_geometry("long", 100.0, 100.0, 99.7)
    assert round(old_pct, 6) == 0.003
    assert round(new_pct, 6) == 0.015
    assert round(stop, 6) == 98.5
    assert round(size, 6) == 20.0
    assert round(size * new_pct, 8) == round(100.0 * old_pct, 8)


def test_atr_stop_is_bounded(monkeypatch):
    live_env(monkeypatch)
    size, stop, _, new_pct = pf._safe_stop_geometry(
        "short", 100.0, 100.0, 100.5, {"atr_pct": 0.02}
    )
    assert round(new_pct, 6) == 0.024
    assert round(stop, 6) == 102.4
    assert size < 100.0


def test_fallback_is_blocked_in_live(monkeypatch):
    live_env(monkeypatch)
    module = ModuleType("bot.nija_core_loop")
    called = {"value": False}

    class NijaCoreLoop:
        def _build_forced_fallback_entry_analysis(self, *args, **kwargs):
            called["value"] = True
            return {"action": "enter_long"}

    module.NijaCoreLoop = NijaCoreLoop
    assert pf._patch_core_loop(module)
    result = NijaCoreLoop()._build_forced_fallback_entry_analysis(
        None, SimpleNamespace(symbol="BTC-USD")
    )
    assert result["action"] == "hold"
    assert result["order_should_not_submit"] is True
    assert called["value"] is False


def test_frequency_relaxation_is_neutralized(monkeypatch):
    live_env(monkeypatch)
    module = ModuleType("bot.trade_frequency_controller")

    @dataclass
    class Drought:
        active: bool
        secs_since_last_trade: float
        adx_reduction: float
        volume_multiplier: float
        score_reduction: float
        gate_pct_reduction: float
        confidence_delta: float
        reason: str

    class TradeFrequencyController:
        def __init__(self):
            self._confidence_delta = -0.35

        def _update_delta(self, now):
            self._confidence_delta = -0.35

        def get_confidence_delta(self):
            return -0.35

        def get_drought_relaxation(self):
            return Drought(True, 999, 6, 0.3, 1.5, 0.35, -0.35, "unsafe")

    module.TradeFrequencyController = TradeFrequencyController
    assert pf._patch_frequency_controller(module)
    controller = TradeFrequencyController()
    assert controller.get_confidence_delta() == 0.0
    drought = controller.get_drought_relaxation()
    assert drought.active is False
    assert drought.volume_multiplier == 1.0
    assert drought.adx_reduction == 0.0


def test_adoption_recovers_cost_basis(monkeypatch):
    live_env(monkeypatch)
    module = ModuleType("bot.live_entry_runtime_fixes")

    def normalize(raw, broker, broker_name, account_id):
        return {
            "symbol": raw["symbol"],
            "entry_price": raw.get("entry_price", raw["mark_price"]),
            "entry_price_source": (
                "broker_cost_basis" if raw.get("entry_price") else "estimated_from_adoption_mark"
            ),
        }

    module._normalize_position = normalize
    assert pf._patch_live_adoption(module)
    pos = module._normalize_position(
        {"symbol": "BTC-USD", "qty": 2, "mark_price": 110, "cost_basis_usd": 200},
        object(),
        "coinbase",
        "platform",
    )
    assert pos["entry_price"] == 100
    assert pos["cost_basis_verified"] is True
    assert pos["auto_exit_blocked"] is False


def test_adoption_without_cost_basis_blocks_automatic_exit(monkeypatch):
    live_env(monkeypatch)
    module = ModuleType("bot.live_entry_runtime_fixes")

    def normalize(raw, broker, broker_name, account_id):
        return {
            "symbol": raw["symbol"],
            "entry_price": raw["mark_price"],
            "entry_price_source": "estimated_from_adoption_mark",
            "stop_loss": 99,
        }

    module._normalize_position = normalize
    pf._patch_live_adoption(module)
    pos = module._normalize_position(
        {"symbol": "ETH-USD", "qty": 1, "mark_price": 100},
        object(),
        "coinbase",
        "platform",
    )
    assert pos["cost_basis_verified"] is False
    assert pos["auto_exit_blocked"] is True
    assert "stop_loss" not in pos
    assert pf._is_unverified_position(pos)


def test_unverified_position_cannot_arm_trailing_tp(monkeypatch):
    live_env(monkeypatch)
    module = ModuleType("bot.trailing_take_profit_runtime_patch")
    module._armed = lambda pos, price: True
    assert pf._patch_exit_module(module)
    assert module._armed({"symbol": "BTC-USD", "cost_basis_verified": False}, 200) is False
    assert module._armed({"symbol": "BTC-USD", "cost_basis_verified": True}, 200) is True


def test_live_entry_requires_positive_fill(monkeypatch):
    live_env(monkeypatch)
    request = SimpleNamespace(intent_type="entry", symbol="BTC-USD")
    bad = SimpleNamespace(success=True, fill_price=0.0, filled_size_usd=10.0, error="")
    out = pf._validate_live_fill_result(bad, request)
    assert out.success is False
    assert "LIVE_FILL_CONFIRMATION_REQUIRED" in out.error
    good = SimpleNamespace(success=True, fill_price=100.0, filled_size_usd=10.0, error="")
    out2 = pf._validate_live_fill_result(good, request)
    assert out2.success is True
    assert out2.fill_confirmed is True
