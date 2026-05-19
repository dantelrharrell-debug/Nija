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
    TradingState,
    TradingStateMachine,
    _collect_live_gate_status,
    _live_activation_gate,
)
from bot.startup_coordinator import get_startup_coordinator


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
    def setUp(self) -> None:
        get_startup_coordinator().reset_for_testing()

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

    def test_runtime_execution_authority_env_is_not_startup_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "false",
                    "DRY_RUN_MODE": "false",
                    "NIJA_RUNTIME_EXECUTION_AUTHORITY": "true",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                snap = sm.get_execution_authority_snapshot(gates_ok=True)
                self.assertFalse(snap["intent_present"])

    def test_startup_coordinator_request_counts_as_activation_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "false",
                    "DRY_RUN_MODE": "false",
                    "NIJA_RUNTIME_EXECUTION_AUTHORITY": "false",
                },
                clear=False,
            ):
                get_startup_coordinator().record_activation_requested(
                    requested=True,
                    source="unit-test",
                )
                sm = TradingStateMachine(state_file=state_path)
                snap = sm.get_execution_authority_snapshot(gates_ok=True)
                self.assertTrue(snap["intent_present"])

    def test_execution_snapshot_includes_runtime_authority_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "false",
                    "DRY_RUN_MODE": "false",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                snap = sm.get_execution_authority_snapshot(gates_ok=True)
                self.assertIn("runtime_authority_state", snap)
                self.assertIn("runtime_authority_reason", snap)
                self.assertIn("execution_permitted", snap)


class TestRuntimeAuthorityRevocation(unittest.TestCase):
    def test_can_dispatch_revoked_when_writer_nonce_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                with sm._lock:
                    sm._current_state = TradingState.LIVE_ACTIVE
                    sm._activation_committed = True
                    sm._execution_authority = True
                    sm._can_dispatch_trades = True

                with patch(
                    "bot.trading_state_machine._is_authority_ready",
                    return_value=True,
                ), patch(
                    "bot.trading_state_machine._runtime_writer_nonce_ready",
                    return_value=(False, "writer_authority:test"),
                ):
                    self.assertFalse(sm.can_dispatch_trades())
                    self.assertFalse(sm.has_execution_authority())


class TestHeartbeatSafetyGating(unittest.TestCase):
    def test_live_gate_status_blocks_execution_when_writer_heartbeat_unhealthy(self) -> None:
        with patch(
            "bot.trading_state_machine._safe_start_gate",
            return_value=(True, ""),
        ), patch(
            "bot.trading_state_machine._startup_reconciliation_gate",
            return_value=(True, ""),
        ), patch(
            "bot.trading_state_machine._nonce_sync_gate",
            return_value=(True, ""),
        ), patch(
            "bot.trading_state_machine._distributed_writer_authority_gate",
            return_value=(True, ""),
        ), patch(
            "bot.trading_state_machine._writer_heartbeat_gate",
            return_value=(False, "writer_heartbeat_stale"),
        ), patch(
            "bot.trading_state_machine._strategy_ready_gate",
            return_value=(True, ""),
        ):
            status = _collect_live_gate_status()
        self.assertFalse(status["heartbeat_ok"])
        self.assertFalse(status["execution_allowed"])

    def test_live_activation_gate_blocks_on_writer_heartbeat(self) -> None:
        ok, reason = _live_activation_gate(
            {
                "safe_ok": True,
                "safe_err": "",
                "recon_ok": True,
                "recon_err": "",
                "nonce_ok": True,
                "nonce_err": "",
                "lease_ok": True,
                "lease_err": "",
                "heartbeat_ok": False,
                "heartbeat_err": "writer_heartbeat_stale",
                "strategy_ok": True,
                "strategy_err": "",
                "execution_allowed": False,
            }
        )
        self.assertFalse(ok)
        self.assertIn("WRITER_HEARTBEAT", reason)


if __name__ == "__main__":
    unittest.main()
