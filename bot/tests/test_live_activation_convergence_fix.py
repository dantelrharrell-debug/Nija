from __future__ import annotations

import importlib
import sys
import threading
import time
import types
from types import SimpleNamespace


def test_preactivation_bootstrap_ready_requires_running_supervised(monkeypatch):
    patch = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    state = SimpleNamespace(value="CAPITAL_READY")
    bootstrap = types.ModuleType("bot.bootstrap_state_machine")
    bootstrap.get_bootstrap_fsm = lambda: SimpleNamespace(state=state)
    monkeypatch.setitem(sys.modules, "bot.bootstrap_state_machine", bootstrap)

    for name in (
        "NIJA_RUNTIME_MODULE_IDENTITY_READY",
        "NIJA_SCAN_WRAPPER_DEPTH_READY",
        "NIJA_ZERO_SIGNAL_STREAK_STATE_READY",
        "NIJA_PRE_DISPATCH_RISK_SIZING_READY",
    ):
        monkeypatch.setenv(name, "1")

    ready, missing = patch._bootstrap_ready()
    assert ready is False
    assert "bootstrap_supervised" in missing
    assert "bootstrap_state:CAPITAL_READY" in missing

    state.value = "RUNNING_SUPERVISED"
    ready, missing = patch._bootstrap_ready()
    assert ready is True
    assert missing == []


def test_stalled_writer_completes_canonical_supervised_handoff(monkeypatch):
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")
    state = SimpleNamespace(value="CAPITAL_READY")
    fsm = SimpleNamespace(
        state=state,
        advance_to_capital_ready=lambda *, reason: True,
    )
    bootstrap = types.ModuleType("bot.bootstrap_state_machine")
    bootstrap.get_bootstrap_fsm = lambda: fsm
    monkeypatch.setitem(sys.modules, "bot.bootstrap_state_machine", bootstrap)

    manager = SimpleNamespace(
        _fsm_initialized=True,
        has_registered_sources=lambda: True,
        has_attempted_connections=lambda: True,
    )
    monkeypatch.setattr(guard, "_manager_instance", lambda: manager)
    monkeypatch.setattr(
        guard,
        "_ingest_authority_snapshot_into_csm",
        lambda source: True,
    )
    monkeypatch.setenv("NIJA_STARTUP_VALIDATED", "1")

    bot_main = types.ModuleType("bot.bot_main")

    def handoff():
        state.value = "RUNNING_SUPERVISED"
        return True

    bot_main._advance_bootstrap_fsm_to_running_supervised = handoff
    monkeypatch.setitem(sys.modules, "bot.bot_main", bot_main)

    assert guard._attempt_bootstrap_progression("unit_test") is True
    assert state.value == "RUNNING_SUPERVISED"


def test_activation_commit_callers_are_serialized():
    module = importlib.import_module("bot.trading_state_machine")
    machine = module.TradingStateMachine.__new__(module.TradingStateMachine)
    machine._activation_commit_lock = threading.RLock()

    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_commit(self, cycle_capital=None):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with state_lock:
            active -= 1
        return True

    machine._commit_activation_unlocked = types.MethodType(fake_commit, machine)
    threads = [
        threading.Thread(target=machine.commit_activation)
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum_active == 1
