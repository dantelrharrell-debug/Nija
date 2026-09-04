from __future__ import annotations

import importlib
import os
import threading
import types
import unittest
from enum import Enum
from unittest import mock


class _State(Enum):
    LIVE_PENDING_CONFIRMATION = "LIVE_PENDING_CONFIRMATION"
    LIVE_ACTIVE = "LIVE_ACTIVE"


class _FakeStateMachine:
    def __init__(self, state: _State) -> None:
        self._lock = threading.Lock()
        self._current_state = state
        self._activation_committed = state == _State.LIVE_ACTIVE
        self._execution_authority = state == _State.LIVE_ACTIVE
        self._core_loop_owns_execution = state != _State.LIVE_ACTIVE
        self._can_dispatch_trades = state == _State.LIVE_ACTIVE
        self._pending_confirmation_since = None
        self._last_pending_log_time = 123.0
        self._pending_timeout_reported = True
        self.persist_calls = 0

    def _persist_state(self) -> None:
        self.persist_calls += 1


class RuntimeStaleLiveExecutionProofV362Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = importlib.import_module("bot.runtime_stale_live_execution_proof_v362_patch")
        self.tsm_module = types.SimpleNamespace(TradingState=_State)
        self.prev_authority = os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        self.prev_state = os.environ.get("NIJA_RUNTIME_TRADING_STATE")

    def tearDown(self) -> None:
        if self.prev_authority is None:
            os.environ.pop("NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
        else:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = self.prev_authority
        if self.prev_state is None:
            os.environ.pop("NIJA_RUNTIME_TRADING_STATE", None)
        else:
            os.environ["NIJA_RUNTIME_TRADING_STATE"] = self.prev_state

    def test_live_active_without_execution_proof_is_demoted_fail_closed(self) -> None:
        sm = _FakeStateMachine(_State.LIVE_ACTIVE)
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ):
            changed = self.patch._revoke_stale_live_authority(
                sm,
                self.tsm_module,
                trigger="test",
            )

        self.assertTrue(changed)
        self.assertEqual(sm._current_state, _State.LIVE_PENDING_CONFIRMATION)
        self.assertFalse(sm._activation_committed)
        self.assertFalse(sm._execution_authority)
        self.assertTrue(sm._core_loop_owns_execution)
        self.assertFalse(sm._can_dispatch_trades)
        self.assertIsNotNone(sm._pending_confirmation_since)
        self.assertIsNone(sm._last_pending_log_time)
        self.assertFalse(sm._pending_timeout_reported)
        self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "0")
        self.assertEqual(os.environ["NIJA_RUNTIME_TRADING_STATE"], "LIVE_PENDING_CONFIRMATION")
        self.assertEqual(sm.persist_calls, 1)

    def test_genuine_canonical_execution_ready_does_not_change_live_state(self) -> None:
        sm = _FakeStateMachine(_State.LIVE_ACTIVE)
        before = (
            sm._current_state,
            sm._activation_committed,
            sm._execution_authority,
            sm._core_loop_owns_execution,
            sm._can_dispatch_trades,
        )
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(True, "canonical_execution_ready"),
        ):
            changed = self.patch._revoke_stale_live_authority(
                sm,
                self.tsm_module,
                trigger="test",
            )

        after = (
            sm._current_state,
            sm._activation_committed,
            sm._execution_authority,
            sm._core_loop_owns_execution,
            sm._can_dispatch_trades,
        )
        self.assertFalse(changed)
        self.assertEqual(after, before)
        self.assertEqual(sm.persist_calls, 0)

    def test_non_live_state_is_not_mutated_when_proof_pending(self) -> None:
        sm = _FakeStateMachine(_State.LIVE_PENDING_CONFIRMATION)
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ):
            changed = self.patch._revoke_stale_live_authority(
                sm,
                self.tsm_module,
                trigger="test",
            )

        self.assertFalse(changed)
        self.assertEqual(sm._current_state, _State.LIVE_PENDING_CONFIRMATION)
        self.assertFalse(sm._execution_authority)
        self.assertFalse(sm._can_dispatch_trades)
        self.assertEqual(sm.persist_calls, 0)

    def test_proof_observer_never_marks_readiness(self) -> None:
        readiness = types.SimpleNamespace(snapshot=lambda: {"execution_ready": False})
        real_import = importlib.import_module

        def fake_import(name: str):
            if name in {"bot.readiness_table", "readiness_table"}:
                return readiness
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import):
            ready, detail = self.patch._canonical_execution_ready()

        self.assertFalse(ready)
        self.assertEqual(detail, "canonical_execution_proof_pending")
        self.assertEqual(readiness.snapshot(), {"execution_ready": False})


if __name__ == "__main__":
    unittest.main()
