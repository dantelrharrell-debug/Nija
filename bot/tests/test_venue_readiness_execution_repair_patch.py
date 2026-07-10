from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import venue_readiness_execution_repair_patch as patch


class _Broker:
    def __init__(self, name: str, connected: bool, balance: float = 0.0):
        self.name = name
        self.connected = connected
        self._last_known_balance = balance


def test_explicit_disconnected_state_wins_over_stale_readiness():
    broker = _Broker("coinbase", connected=False, balance=99.0)
    broker.is_ready_for_capital = lambda: True

    assert patch._broker_execution_ready(broker) is False


def test_capital_refresh_excludes_disconnected_platform_broker_and_restores_registry():
    module = ModuleType("fake_multi_account_broker_manager")

    class MultiAccountBrokerManager:
        def __init__(self):
            self._platform_brokers = {
                "kraken": _Broker("kraken", connected=True, balance=120.0),
                "coinbase": _Broker("coinbase", connected=False, balance=0.0),
            }

        def refresh_capital_authority(self, trigger="manual"):
            return {
                "trigger": trigger,
                "eligible": sorted(self._platform_brokers),
                "valid_brokers": len(self._platform_brokers),
            }

    module.MultiAccountBrokerManager = MultiAccountBrokerManager
    assert patch._patch_mabm_module(module)

    manager = MultiAccountBrokerManager()
    original_registry = manager._platform_brokers
    result = manager.refresh_capital_authority(trigger="watchdog")

    assert result["eligible"] == ["kraken"]
    assert result["valid_brokers"] == 1
    assert manager._platform_brokers is original_registry
    assert sorted(manager._platform_brokers) == ["coinbase", "kraken"]


def _fake_independent_module(kraken: _Broker | None):
    module = ModuleType("fake_broker_independent")
    module._WRAP_ATTR = "_fake_independent_wrapped"
    module._collect_candidate_brokers = lambda apex, explicit: {
        **({"coinbase": explicit} if explicit is not None else {}),
        **({"kraken": kraken} if kraken is not None else {}),
    }
    module._csv_env = lambda name, default: ["okx", "coinbase", "kraken"]
    module._broker_entry_balance = lambda name, broker, fallback: broker._last_known_balance
    module._broker_position_count = lambda broker, fallback: 0
    return module


def _fake_core_module():
    module = ModuleType("fake_nija_core_loop")

    class CoreLoopResult:
        pass

    class NijaCoreLoop:
        def __init__(self, apex):
            self.apex = apex

        def run_scan_phase(self, broker, balance, symbols, open_positions_count=0, user_mode=False):
            return SimpleNamespace(
                called_broker=broker,
                called_balance=balance,
                entries_taken=0,
                entries_blocked=0,
                symbols_scored=len(symbols),
                exits_taken=0,
                errors=[],
                next_interval=150,
            )

    setattr(NijaCoreLoop.run_scan_phase, "_fake_independent_wrapped", True)
    module.CoreLoopResult = CoreLoopResult
    module.NijaCoreLoop = NijaCoreLoop
    return module


def test_disconnected_scan_caller_is_rerouted_to_connected_kraken():
    coinbase = _Broker("coinbase", connected=False, balance=0.0)
    kraken = _Broker("kraken", connected=True, balance=88.5)
    independent = _fake_independent_module(kraken)
    core = _fake_core_module()

    assert patch._patch_independent_module(independent)
    assert patch._patch_core_module(core, independent)

    loop = core.NijaCoreLoop(SimpleNamespace())
    result = loop.run_scan_phase(coinbase, 336.0, ["BTC-USD"])

    assert result.called_broker is kraken
    assert result.called_balance == 88.5


def test_disconnected_scan_caller_returns_clean_noop_when_no_venue_is_ready():
    coinbase = _Broker("coinbase", connected=False, balance=0.0)
    independent = _fake_independent_module(None)
    core = _fake_core_module()

    assert patch._patch_independent_module(independent)
    assert patch._patch_core_module(core, independent)

    loop = core.NijaCoreLoop(SimpleNamespace())
    result = loop.run_scan_phase(coinbase, 336.0, ["BTC-USD"])

    assert result.entries_taken == 0
    assert result.entries_blocked == 0
    assert result.symbols_scored == 0
    assert result.errors == []


def test_late_okx_binding_targets_broker_and_router_modules(monkeypatch):
    broker_manager = ModuleType("bot.broker_manager")
    broker_integration = ModuleType("bot.broker_integration")
    router = ModuleType("bot.multi_broker_execution_router")
    bridge = ModuleType("bot.okx_final_order_submission_bridge_patch")
    seen = []

    def _patch_module(target):
        seen.append(target.__name__)
        if target is router:
            bridge._ROUTER_PATCHED = True
        if target is broker_integration:
            bridge._PATCHED_ORDER_CLASSES.add("bot.broker_integration.OKXBrokerAdapter.place_market_order")
        return True

    bridge._ROUTER_PATCHED = False
    bridge._PATCHED_ORDER_CLASSES = set()
    bridge._patch_module = _patch_module

    monkeypatch.setitem(sys.modules, "bot.broker_manager", broker_manager)
    monkeypatch.setitem(sys.modules, "bot.broker_integration", broker_integration)
    monkeypatch.setitem(sys.modules, "bot.multi_broker_execution_router", router)
    monkeypatch.setitem(sys.modules, "bot.okx_final_order_submission_bridge_patch", bridge)

    assert patch._bind_okx_bridge_once() is True
    assert "bot.broker_manager" in seen
    assert "bot.broker_integration" in seen
    assert "bot.multi_broker_execution_router" in seen
    assert bridge._ROUTER_PATCHED is True
    assert bridge._PATCHED_ORDER_CLASSES
