from __future__ import annotations

from types import SimpleNamespace

from bot import trading_strategy_apex_wiring_patch as patch


class FakeStrategy:
    def __init__(self):
        self.apex = None
        self.nija_core_loop = None
        self.broker = SimpleNamespace(connected=True)
        self.execution_engine = None

    def _ensure_nija_wiring(self):
        return None

    def run_cycle(self, broker=None, user_mode=False):
        return 90


def test_lazy_getattribute_hydrates_apex_before_core_loop_guard(monkeypatch):
    calls: list[str] = []

    def fake_hydrate(strategy, broker=None, reason="runtime"):
        calls.append(reason)
        object.__setattr__(strategy, "apex", SimpleNamespace(execution_engine="ee"))
        object.__setattr__(strategy, "nija_core_loop", SimpleNamespace(apex=strategy.apex))
        object.__setattr__(strategy, "execution_engine", "ee")
        return True

    monkeypatch.setattr(patch, "_bounded_hydrate_strategy_wiring", fake_hydrate)
    module = SimpleNamespace(TradingStrategy=FakeStrategy, __name__="bot.trading_strategy")

    assert patch._install_on_module(module) is True
    strategy = module.TradingStrategy()
    object.__setattr__(strategy, "apex", None)
    object.__setattr__(strategy, "nija_core_loop", None)

    # This mirrors nija_core_loop.py: getattr(strategy, "apex", None)
    # must hydrate before the core loop declares RUN_CYCLE_BLOCKED_MISSING_REF.
    assert getattr(strategy, "apex", None) is not None
    assert getattr(strategy, "nija_core_loop", None) is not None
    assert any(reason.startswith("lazy_getattribute:apex") for reason in calls)


def test_ensure_nija_wiring_hydrates_when_apex_missing(monkeypatch):
    calls: list[str] = []

    def fake_hydrate(strategy, broker=None, reason="runtime"):
        calls.append(reason)
        object.__setattr__(strategy, "apex", SimpleNamespace(execution_engine="ee"))
        object.__setattr__(strategy, "nija_core_loop", SimpleNamespace(apex=strategy.apex))
        return True

    monkeypatch.setattr(patch, "_bounded_hydrate_strategy_wiring", fake_hydrate)
    module = SimpleNamespace(TradingStrategy=FakeStrategy, __name__="bot.trading_strategy")

    assert patch._install_on_module(module) is True
    strategy = module.TradingStrategy()
    object.__setattr__(strategy, "apex", None)
    object.__setattr__(strategy, "nija_core_loop", None)

    strategy._ensure_nija_wiring()

    assert getattr(strategy, "apex", None) is not None
    assert getattr(strategy, "nija_core_loop", None) is not None


def test_run_cycle_hydrates_before_delegating(monkeypatch):
    calls: list[str] = []

    def fake_hydrate(strategy, broker=None, reason="runtime"):
        calls.append(reason)
        object.__setattr__(strategy, "apex", SimpleNamespace(execution_engine="ee"))
        object.__setattr__(strategy, "nija_core_loop", SimpleNamespace(apex=strategy.apex))
        return True

    monkeypatch.setattr(patch, "_bounded_hydrate_strategy_wiring", fake_hydrate)
    module = SimpleNamespace(TradingStrategy=FakeStrategy, __name__="bot.trading_strategy")

    assert patch._install_on_module(module) is True
    strategy = module.TradingStrategy()
    object.__setattr__(strategy, "apex", None)
    object.__setattr__(strategy, "nija_core_loop", None)

    assert strategy.run_cycle() == 90
    assert getattr(strategy, "apex", None) is not None
    assert getattr(strategy, "nija_core_loop", None) is not None
