from __future__ import annotations

import importlib
import os
import threading
from types import SimpleNamespace


def _fresh_module():
    module = importlib.import_module("bot.runtime_stale_live_execution_proof_v362_patch")
    return importlib.reload(module)


def test_get_current_state_demotes_stale_live_without_execution_proof(monkeypatch):
    patch = _fresh_module()
    tsm = importlib.import_module("bot.trading_state_machine")
    original_import = importlib.import_module

    monkeypatch.setattr(patch, "_canonical_execution_ready", lambda: (False, "canonical_execution_proof_pending"))

    class FakeMachine:
        _lock = threading.RLock()
        _current_state = tsm.TradingState.LIVE_ACTIVE
        _activation_committed = True
        _execution_authority = True
        _core_loop_owns_execution = True
        _can_dispatch_trades = True
        _pending_confirmation_since = 0.0
        _last_pending_log_time = 1.0
        _pending_timeout_reported = True

        def _persist_state(self):
            self.persisted = True

        def get_current_state(self):
            return self._current_state

        def commit_activation(self, *args, **kwargs):
            return True

        def activate_live_trading(self, *args, **kwargs):
            return True

    fake_module = SimpleNamespace(
        TradingState=tsm.TradingState,
        TradingStateMachine=FakeMachine,
        _state_machine=None,
    )
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake_module if name == "bot.trading_state_machine" else original_import(name),
    )

    assert patch._patch_trading_state_machine() is True
    machine = FakeMachine()
    state = machine.get_current_state()

    assert state == tsm.TradingState.LIVE_PENDING_CONFIRMATION
    assert machine._activation_committed is False
    assert machine._execution_authority is False
    assert machine._can_dispatch_trades is False
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == tsm.TradingState.LIVE_PENDING_CONFIRMATION.value


def test_get_current_state_preserves_live_when_canonical_execution_ready(monkeypatch):
    patch = _fresh_module()
    tsm = importlib.import_module("bot.trading_state_machine")
    original_import = importlib.import_module

    monkeypatch.setattr(patch, "_canonical_execution_ready", lambda: (True, "canonical_execution_ready"))

    class FakeMachine:
        _lock = threading.RLock()
        _current_state = tsm.TradingState.LIVE_ACTIVE
        _activation_committed = True
        _execution_authority = True
        _core_loop_owns_execution = True
        _can_dispatch_trades = True

        def get_current_state(self):
            return self._current_state

        def commit_activation(self, *args, **kwargs):
            return True

        def activate_live_trading(self, *args, **kwargs):
            return True

    fake_module = SimpleNamespace(
        TradingState=tsm.TradingState,
        TradingStateMachine=FakeMachine,
        _state_machine=None,
    )
    monkeypatch.setattr(
        patch.importlib,
        "import_module",
        lambda name: fake_module if name == "bot.trading_state_machine" else original_import(name),
    )

    assert patch._patch_trading_state_machine() is True
    machine = FakeMachine()
    assert machine.get_current_state() == tsm.TradingState.LIVE_ACTIVE
    assert machine._activation_committed is True
    assert machine._execution_authority is True
    assert machine._can_dispatch_trades is True
