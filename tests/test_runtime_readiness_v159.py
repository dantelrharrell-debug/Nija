from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from bot import runtime_quality_convergence_v157_patch as patch


def test_capital_deadline_adds_post_fetch_headroom_inside_freshness():
    assert patch._capital_deadline_value(70.0, 90.0, 50.0) == 80.0


def test_capital_deadline_never_crosses_freshness_safety_margin():
    assert patch._capital_deadline_value(120.0, 90.0, 50.0) == 80.0


def test_capital_deadline_preserves_stricter_small_ttl_bound():
    assert patch._capital_deadline_value(18.0, 30.0, 20.0) == 20.0


def _fake_tsm(state: str, requested: bool = True):
    module = ModuleType("bot.trading_state_machine")
    calls: list[str] = []

    class FakeSM:
        def get_current_state(self):
            return SimpleNamespace(value=state)

    class FakeCoordinator:
        def build_snapshot(self, *, trading_state: str, activation_intent: bool):
            calls.append(trading_state)
            return SimpleNamespace(activation_intent=requested)

    module.get_trading_state_machine = lambda: FakeSM()
    module._get_startup_coordinator = lambda: FakeCoordinator()
    module._env_truthy = lambda name: False

    def original(runtime_mode=None):
        return False

    module._activation_intent_present = original
    return module, calls


def test_activation_intent_probe_uses_live_active_not_unknown(monkeypatch):
    fake, calls = _fake_tsm("LIVE_ACTIVE")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", fake)
    assert patch._patch_activation_intent_state_source() is True
    assert fake._activation_intent_present() is True
    assert calls == ["LIVE_ACTIVE"]


def test_activation_intent_probe_preserves_explicit_off(monkeypatch):
    fake, calls = _fake_tsm("OFF")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", fake)
    assert patch._patch_activation_intent_state_source() is True
    assert fake._activation_intent_present() is True
    assert calls == ["OFF"]


def test_activation_intent_probe_preserves_emergency_stop(monkeypatch):
    fake, calls = _fake_tsm("EMERGENCY_STOP")
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", fake)
    assert patch._patch_activation_intent_state_source() is True
    assert fake._activation_intent_present() is True
    assert calls == ["EMERGENCY_STOP"]


def test_activation_intent_probe_falls_back_to_off_not_live(monkeypatch):
    fake, calls = _fake_tsm("UNKNOWN")
    monkeypatch.delenv("NIJA_RUNTIME_TRADING_STATE", raising=False)
    monkeypatch.setitem(sys.modules, "bot.trading_state_machine", fake)
    assert patch._patch_activation_intent_state_source() is True
    assert fake._activation_intent_present() is True
    assert calls == ["OFF"]


def test_v142_deadline_wrapper_leaves_generation_fence_untouched(monkeypatch):
    module = ModuleType("bot.capital_publication_liveness_v142_patch")
    original_retire = object()
    module._retire_generation = original_retire
    module._runtime_pipeline_deadline_seconds = lambda: 70.0
    module._freshness_ttl_seconds = lambda: 90.0
    module._fetch_budget_seconds = lambda: 50.0
    monkeypatch.setitem(sys.modules, "bot.capital_publication_liveness_v142_patch", module)

    assert patch._patch_capital_pipeline_deadline_headroom() is True
    assert module._runtime_pipeline_deadline_seconds() == 80.0
    assert module._retire_generation is original_retire
