from __future__ import annotations

import importlib
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

_ENV_KEYS = (
    "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    "NIJA_RUNTIME_TRADING_STATE",
    "NIJA_RUNTIME_STALE_LIVE_EXECUTION_PROOF_V362_READY",
)


def _fresh_module():
    module = importlib.import_module("bot.runtime_stale_live_execution_proof_v362_patch")
    return importlib.reload(module)


class RuntimeStaleLiveExecutionProofV362ReadGuardTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_get_current_state_demotes_stale_live_without_execution_proof(self):
        patch = _fresh_module()
        tsm = importlib.import_module("bot.trading_state_machine")
        original_import = importlib.import_module

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

        with mock.patch.object(
            patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ), mock.patch.object(
            patch.importlib,
            "import_module",
            side_effect=lambda name: fake_module if name == "bot.trading_state_machine" else original_import(name),
        ):
            self.assertTrue(patch._patch_trading_state_machine())
            machine = FakeMachine()
            state = machine.get_current_state()

        self.assertEqual(state, tsm.TradingState.LIVE_PENDING_CONFIRMATION)
        self.assertFalse(machine._activation_committed)
        self.assertFalse(machine._execution_authority)
        self.assertFalse(machine._can_dispatch_trades)
        self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "0")
        self.assertEqual(
            os.environ["NIJA_RUNTIME_TRADING_STATE"],
            tsm.TradingState.LIVE_PENDING_CONFIRMATION.value,
        )

    def test_get_current_state_preserves_live_when_canonical_execution_ready(self):
        patch = _fresh_module()
        tsm = importlib.import_module("bot.trading_state_machine")
        original_import = importlib.import_module

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

        with mock.patch.object(
            patch,
            "_canonical_execution_ready",
            return_value=(True, "canonical_execution_ready"),
        ), mock.patch.object(
            patch.importlib,
            "import_module",
            side_effect=lambda name: fake_module if name == "bot.trading_state_machine" else original_import(name),
        ):
            self.assertTrue(patch._patch_trading_state_machine())
            machine = FakeMachine()
            state = machine.get_current_state()

        self.assertEqual(state, tsm.TradingState.LIVE_ACTIVE)
        self.assertTrue(machine._activation_committed)
        self.assertTrue(machine._execution_authority)
        self.assertTrue(machine._can_dispatch_trades)

    def test_missing_read_hook_keeps_commit_and_activation_guards_installed(self):
        patch = _fresh_module()
        tsm = importlib.import_module("bot.trading_state_machine")
        original_import = importlib.import_module

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

            def commit_activation(self, *args, **kwargs):
                return True

            def activate_live_trading(self, *args, **kwargs):
                return True

        fake_module = SimpleNamespace(
            TradingState=tsm.TradingState,
            TradingStateMachine=FakeMachine,
            _state_machine=None,
        )

        with mock.patch.object(
            patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ), mock.patch.object(
            patch.importlib,
            "import_module",
            side_effect=lambda name: fake_module if name == "bot.trading_state_machine" else original_import(name),
        ):
            # Read-guard readiness remains fail-closed, but the older safety
            # wrappers must still be installed rather than skipped wholesale.
            self.assertFalse(patch._patch_trading_state_machine())
            self.assertTrue(getattr(FakeMachine.commit_activation, patch._PATCH_ATTR, False))
            self.assertTrue(getattr(FakeMachine.activate_live_trading, patch._PATCH_ATTR, False))

            machine = FakeMachine()
            self.assertFalse(machine.commit_activation())

        self.assertEqual(machine._current_state, tsm.TradingState.LIVE_PENDING_CONFIRMATION)
        self.assertFalse(machine._activation_committed)
        self.assertFalse(machine._execution_authority)
        self.assertFalse(machine._can_dispatch_trades)


if __name__ == "__main__":
    unittest.main()
