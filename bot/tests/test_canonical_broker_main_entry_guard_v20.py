from __future__ import annotations

import types

import bot.canonical_broker_main_entry_guard_v20 as guard


class LatchBlockedManager:
    def __init__(self):
        self._fsm_initialized = False
        self.initialize_calls = 0
        self.repair_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        if not self._fsm_initialized:
            raise RuntimeError("BrokerManager not initialized")

    def _init_capital_fsm(self):
        self.repair_calls += 1
        self._fsm_initialized = True


def test_initialize_manager_repairs_stale_fsm_latch_and_retries():
    manager = LatchBlockedManager()

    guard._initialize_manager(manager)

    assert manager._fsm_initialized is True
    assert manager.repair_calls == 1
    assert manager.initialize_calls == 2


def test_unwrap_legacy_startup_returns_original_function():
    def original():
        return True, object(), "kraken"

    def wrapper():
        return original()

    wrapper.__wrapped__ = original

    assert guard._unwrap_legacy_startup(wrapper) is original


def test_main_guard_repatches_startup_immediately_before_execution(monkeypatch):
    module = types.ModuleType("bot.bot_main")
    broker = object()

    def original_startup():
        return True, broker, "kraken"

    module._run_self_healing_startup = original_startup
    module.main = lambda: module._run_self_healing_startup()

    monkeypatch.setattr(
        guard,
        "_initialize_canonical_runtime",
        lambda connected_broker, name: (True, connected_broker, name),
    )

    assert guard._patch_startup(module)
    assert guard._patch_main(module)

    # Simulate a later import hook replacing the startup wrapper. The guarded
    # main function must restore the canonical handoff before bot_main executes.
    module._run_self_healing_startup = original_startup

    assert module.main() == (True, broker, "kraken")
    assert getattr(
        module._run_self_healing_startup,
        guard._STARTUP_WRAP_ATTR,
        False,
    ) is True
