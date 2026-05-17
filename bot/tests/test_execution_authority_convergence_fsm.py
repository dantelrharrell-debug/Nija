"""Tests for dual-layer execution authority convergence FSM behavior."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from bot.trading_state_machine import (
    ExecutionAuthorityConvergenceFSM,
    ExecutionProgressState,
    ExecutionSafetyState,
    TradingStateMachine,
)


class TestExecutionAuthorityConvergenceFSM(unittest.TestCase):
    def test_locked_when_intent_missing(self) -> None:
        fsm = ExecutionAuthorityConvergenceFSM(timeout_s=2.0)
        snap = fsm.evaluate(
            intent_present=False,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=True,
            activation_committed=True,
            execution_authority=True,
            can_dispatch_trades=True,
            gates_ok=True,
            now_monotonic=1.0,
        )
        self.assertEqual(snap.progress_state, ExecutionProgressState.LOCKED)
        self.assertEqual(snap.safety_state, ExecutionSafetyState.LOCKED)

    def test_armed_until_bootstrap_and_capital_running(self) -> None:
        fsm = ExecutionAuthorityConvergenceFSM(timeout_s=2.0)
        snap = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=False,
            capital_running=True,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=True,
            now_monotonic=1.0,
        )
        self.assertEqual(snap.progress_state, ExecutionProgressState.ARMED)
        self.assertEqual(snap.safety_state, ExecutionSafetyState.LOCKED)

    def test_blocked_retry_transitions_to_fail_safe_after_timeout(self) -> None:
        fsm = ExecutionAuthorityConvergenceFSM(timeout_s=1.0)
        snap1 = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=False,
            now_monotonic=10.0,
        )
        self.assertEqual(snap1.progress_state, ExecutionProgressState.BLOCKED_RETRY)
        snap2 = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=False,
            now_monotonic=11.1,
        )
        self.assertEqual(snap2.progress_state, ExecutionProgressState.FAIL_SAFE)
        self.assertEqual(snap2.safety_state, ExecutionSafetyState.LOCKED)

    def test_blocked_retry_recovers_to_authorized(self) -> None:
        fsm = ExecutionAuthorityConvergenceFSM(timeout_s=5.0)
        fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=False,
            now_monotonic=20.0,
        )
        snap2 = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=False,
            activation_committed=False,
            execution_authority=False,
            can_dispatch_trades=False,
            gates_ok=True,
            now_monotonic=21.0,
        )
        self.assertEqual(snap2.progress_state, ExecutionProgressState.CONVERGING)
        snap3 = fsm.evaluate(
            intent_present=True,
            bootstrap_running_supervised=True,
            capital_running=True,
            trading_live=True,
            activation_committed=True,
            execution_authority=True,
            can_dispatch_trades=True,
            gates_ok=True,
            now_monotonic=21.1,
        )
        self.assertEqual(snap3.progress_state, ExecutionProgressState.AUTHORIZED)
        self.assertEqual(snap3.safety_state, ExecutionSafetyState.AUTHORIZED)
        self.assertTrue(snap3.converged)


class TestMaybeAutoActivateDelegation(unittest.TestCase):
    def test_maybe_auto_activate_delegates_to_commit_activation_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "false",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "FORCE_LIVE_TRANSITION": "false",
                    "HEARTBEAT_TRADE": "false",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                with patch.object(sm, "commit_activation", return_value=False) as mock_commit:
                    self.assertFalse(sm.maybe_auto_activate())
                    mock_commit.assert_called_once_with(cycle_capital=None)


if __name__ == "__main__":
    unittest.main()
