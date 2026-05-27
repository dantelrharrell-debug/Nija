"""Tests for dual-layer execution authority convergence FSM behavior."""

from __future__ import annotations

import json
import os
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from bot.trading_state_machine import (
    ExecutionAuthorityConvergenceFSM,
    ExecutionProgressState,
    ExecutionSafetyState,
    TradingState,
    TradingStateMachine,
    _collect_live_gate_status,
    _heartbeat_verification_required,
    _live_activation_gate,
    _writer_heartbeat_gate,
)
from bot.startup_coordinator import get_startup_coordinator
from bot import readiness_table


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

    def test_startup_override_blocks_live_arming_without_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "FORCE_LIVE_TRANSITION": "false",
                    "HEARTBEAT_TRADE": "false",
                },
                clear=False,
            ), patch(
                "bot.trading_state_machine._startup_ownership_gate",
                return_value=(False, "bootstrap_guard_not_held"),
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertEqual(sm.get_current_state(), TradingState.OFF)

    def test_startup_override_arms_live_when_ownership_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "FORCE_LIVE_TRANSITION": "false",
                    "HEARTBEAT_TRADE": "false",
                },
                clear=False,
            ), patch(
                "bot.trading_state_machine._startup_ownership_gate",
                return_value=(True, ""),
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertEqual(sm.get_current_state(), TradingState.LIVE_PENDING_CONFIRMATION)

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
                self.assertIn("runtime_lifecycle_phase", snap)
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


class _StubCapitalAuthority:
    is_hydrated = True

    @staticmethod
    def get_real_capital():
        return 100.0

    @staticmethod
    def is_stale():
        return False


class TestCommitActivationConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        get_startup_coordinator().reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        get_startup_coordinator().reset_for_testing()
        readiness_table.reset()

    def test_parallel_commit_activation_emits_single_dispatch_enabled_phase_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            readiness_snapshot = {k: True for k in readiness_table.KEYS}
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "LIVE_TRADING": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "NIJA_WRITER_FENCING_TOKEN": "unit-test-token",
                },
                clear=False,
            ), patch("bot.trading_state_machine._heartbeat_verification_required", return_value=False), patch(
                "bot.trading_state_machine._collect_live_gate_status",
                return_value={"lease_ok": True, "nonce_ok": True, "lease_err": "", "nonce_err": ""},
            ), patch(
                "bot.trading_state_machine._live_activation_gate",
                return_value=(True, ""),
            ), patch(
                "bot.trading_state_machine._nonce_writer_lease_gate",
                return_value=(True, ""),
            ), patch(
                "bot.trading_state_machine._get_capital_authority_instance",
                return_value=_StubCapitalAuthority(),
            ), patch(
                "bot.trading_state_machine._capital_bootstrap_state_value",
                return_value="RUNNING",
            ), patch(
                "bot.trading_state_machine._bootstrap_state_value",
                return_value="RUNNING_SUPERVISED",
            ), patch(
                "bot.trading_state_machine._readiness_snapshot_with_version",
                return_value=(1, readiness_snapshot),
            ), patch(
                "bot.trading_state_machine._global_activation_barrier",
                return_value=(True, "ok", True, True, True, True),
            ), patch(
                "bot.trading_state_machine._is_authority_ready",
                return_value=True,
            ), patch(
                "bot.trading_state_machine._distributed_writer_authority_gate",
                return_value=(True, ""),
            ), patch(
                "bot.revocation_guard.check_revocation_or_raise",
                return_value=None,
            ):
                sm = TradingStateMachine(state_file=state_path)
                coordinator = get_startup_coordinator()
                coordinator.record_threads_launched(1)
                coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
                results: list[bool] = []
                errors: list[str] = []

                def _run() -> None:
                    try:
                        results.append(bool(sm.commit_activation(cycle_capital={"ca_valid_brokers": 1, "snapshot_source": "live_exchange"})))
                    except Exception as exc:  # pragma: no cover - defensive
                        errors.append(str(exc))

                t1 = threading.Thread(target=_run, daemon=True)
                t2 = threading.Thread(target=_run, daemon=True)
                t1.start()
                t2.start()
                t1.join(timeout=3)
                t2.join(timeout=3)

                self.assertEqual(errors, [])
                self.assertEqual(len(results), 2)
                self.assertTrue(all(results))
                history = coordinator.get_history()
                dispatch_enabled_phase_events = [
                    e
                    for e in history
                    if e.get("event") == "DISPATCH_ENABLED"
                    and e.get("payload", {}).get("phase") == "DISPATCH_ENABLED"
                ]
                self.assertEqual(len(dispatch_enabled_phase_events), 1)


class TestHeartbeatSafetyGating(unittest.TestCase):
    def test_writer_heartbeat_gate_allows_manual_active_override_without_timestamp(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NIJA_ENFORCE_WRITER_HEARTBEAT_GATE": "true",
                "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            },
            clear=False,
        ):
            os.environ.pop("NIJA_WRITER_HEARTBEAT_ALIVE_TS", None)
            ok, reason = _writer_heartbeat_gate()
            self.assertTrue(ok)
            self.assertEqual(reason, "")
            self.assertGreater(float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0")), 0.0)

    def test_writer_heartbeat_gate_bootstraps_monitor_when_default_flag_zero(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NIJA_ENFORCE_WRITER_HEARTBEAT_GATE": "true",
                "NIJA_WRITER_HEARTBEAT_ACTIVE": "0",
            },
            clear=False,
        ):
            os.environ.pop("NIJA_WRITER_HEARTBEAT_ALIVE_TS", None)

            def _start_monitor() -> None:
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
                os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = str(time.time())

            with patch(
                "bot.authority_heartbeat.start_authority_heartbeat",
                side_effect=_start_monitor,
            ) as start_mock:
                ok, reason = _writer_heartbeat_gate()

            self.assertTrue(ok)
            self.assertEqual(reason, "")
            start_mock.assert_called_once()

    def test_writer_heartbeat_gate_allows_one_bootstrap_cycle_then_blocks_if_flag_stays_zero(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NIJA_ENFORCE_WRITER_HEARTBEAT_GATE": "true",
                "NIJA_WRITER_HEARTBEAT_ACTIVE": "0",
            },
            clear=False,
        ):
            os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
            os.environ.pop("NIJA_WRITER_HEARTBEAT_BOOTSTRAP_PENDING", None)
            with patch("bot.authority_heartbeat.start_authority_heartbeat", return_value=None):
                first_ok, first_reason = _writer_heartbeat_gate()
                second_ok, second_reason = _writer_heartbeat_gate()

            self.assertTrue(first_ok)
            self.assertEqual(first_reason, "")
            self.assertEqual(os.environ.get("NIJA_WRITER_HEARTBEAT_BOOTSTRAP_PENDING"), "1")
            self.assertFalse(second_ok)
            self.assertEqual(second_reason, "writer_heartbeat_inactive")

    def test_heartbeat_verification_required_when_heartbeat_trade_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HEARTBEAT_REQUIRED_FIRST_ACTIVATION": "false",
                "HEARTBEAT_TRADE": "true",
            },
            clear=False,
        ):
            self.assertTrue(_heartbeat_verification_required())

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

    def test_commit_activation_blocks_when_heartbeat_trade_enabled_and_marker_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "missing-heartbeat.flag")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_REQUIRED_FIRST_ACTIVATION": "false",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertFalse(sm.commit_activation())

    def test_commit_activation_arms_pending_when_off_with_live_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "HEARTBEAT_TRADE": "false",
                    "HEARTBEAT_REQUIRED_FIRST_ACTIVATION": "false",
                },
                clear=False,
            ), patch(
                "bot.trading_state_machine._startup_ownership_gate",
                return_value=(False, "bootstrap_guard_not_held"),
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertEqual(sm.get_current_state(), TradingState.OFF)

                class _ReadyCA:
                    is_hydrated = True

                    @staticmethod
                    def get_real_capital() -> float:
                        return 131.11

                    @staticmethod
                    def is_stale() -> bool:
                        return False

                with patch(
                    "bot.authority_heartbeat.start_authority_heartbeat",
                    return_value=None,
                ), patch(
                    "bot.trading_state_machine._collect_live_gate_status",
                    return_value={
                        "safe_ok": True,
                        "safe_err": "",
                        "recon_ok": True,
                        "recon_err": "",
                        "nonce_ok": True,
                        "nonce_err": "",
                        "lease_ok": True,
                        "lease_err": "",
                        "heartbeat_ok": True,
                        "heartbeat_err": "",
                        "strategy_ok": True,
                        "strategy_err": "",
                        "breaker_ok": True,
                        "breaker_err": "",
                        "execution_allowed": True,
                    },
                ), patch(
                    "bot.trading_state_machine._live_activation_gate",
                    return_value=(True, ""),
                ), patch(
                    "bot.trading_state_machine._is_authority_ready",
                    return_value=True,
                ), patch(
                    "bot.trading_state_machine._nonce_writer_lease_gate",
                    return_value=(True, ""),
                ), patch(
                    "bot.trading_state_machine._capital_bootstrap_state_value",
                    return_value="RUNNING",
                ), patch(
                    "bot.trading_state_machine._bootstrap_state_value",
                    return_value="RUNNING_SUPERVISED",
                ), patch(
                    "bot.trading_state_machine._readiness_snapshot_with_version",
                    return_value=(1, {"authority_ready": True, "nonce_ready": True}),
                ), patch(
                    "bot.trading_state_machine._get_capital_authority_instance",
                    return_value=_ReadyCA(),
                ), patch(
                    "bot.trading_state_machine._global_activation_barrier",
                    return_value=(False, "execution pipeline pending", True, False, True, False),
                ):
                    self.assertFalse(sm.commit_activation(cycle_capital={"ca_total_capital": 131.11}))
                    self.assertEqual(sm.get_current_state(), TradingState.LIVE_PENDING_CONFIRMATION)

    def test_commit_activation_does_not_arm_pending_without_live_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "false",
                    "LIVE_TRADING": "false",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "false",
                    "HEARTBEAT_TRADE": "false",
                    "HEARTBEAT_REQUIRED_FIRST_ACTIVATION": "false",
                },
                clear=False,
            ), patch(
                "bot.trading_state_machine._startup_ownership_gate",
                return_value=(False, "bootstrap_guard_not_held"),
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertEqual(sm.get_current_state(), TradingState.OFF)

                with patch(
                    "bot.authority_heartbeat.start_authority_heartbeat",
                    return_value=None,
                ), patch(
                    "bot.trading_state_machine._activation_intent_present",
                    return_value=False,
                ), patch(
                    "bot.trading_state_machine._collect_live_gate_status",
                    return_value={
                        "safe_ok": True,
                        "safe_err": "",
                        "recon_ok": True,
                        "recon_err": "",
                        "nonce_ok": True,
                        "nonce_err": "",
                        "lease_ok": True,
                        "lease_err": "",
                        "heartbeat_ok": True,
                        "heartbeat_err": "",
                        "strategy_ok": True,
                        "strategy_err": "",
                        "breaker_ok": True,
                        "breaker_err": "",
                        "execution_allowed": True,
                    },
                ), patch(
                    "bot.trading_state_machine._live_activation_gate",
                    return_value=(True, ""),
                ), patch(
                    "bot.trading_state_machine._is_authority_ready",
                    return_value=False,
                ), patch(
                    "bot.trading_state_machine._global_activation_barrier",
                    return_value=(False, "execution pipeline pending", True, False, True, False),
                ):
                    self.assertFalse(sm.commit_activation(cycle_capital={"ca_total_capital": 131.11}))
                    self.assertEqual(sm.get_current_state(), TradingState.OFF)
                    self.assertEqual(os.environ.get("NIJA_RUNTIME_TRADING_STATE"), TradingState.OFF.value)

    def test_commit_activation_blocks_when_heartbeat_marker_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "heartbeat_verified.flag")
            stale_payload = {
                "verified": True,
                "version": 2,
                "stage": "FILL_VERIFY",
                "verified_at_epoch": time.time() - 7200,
            }
            with open(marker_path, "w", encoding="utf-8") as marker_file:
                marker_file.write(json.dumps(stale_payload))
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS": "3600",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertFalse(sm.commit_activation())

    def test_commit_activation_passes_when_heartbeat_marker_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "heartbeat_verified.flag")
            payload = {
                "verified": True,
                "version": 2,
                "stage": "ORDER_VERIFY",
                "verified_at_epoch": time.time(),
            }
            with open(marker_path, "w", encoding="utf-8") as marker_file:
                marker_file.write(json.dumps(payload))
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS": "3600",
                    "HEARTBEAT_VERIFICATION_REQUIRED_STAGE": "ORDER_VERIFY",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                with patch(
                    "bot.trading_state_machine._collect_live_gate_status",
                    return_value={
                        "safe_ok": True,
                        "safe_err": "",
                        "recon_ok": True,
                        "recon_err": "",
                        "nonce_ok": True,
                        "nonce_err": "",
                        "lease_ok": True,
                        "lease_err": "",
                        "heartbeat_ok": True,
                        "heartbeat_err": "",
                        "strategy_ok": True,
                        "strategy_err": "",
                        "breaker_ok": True,
                        "breaker_err": "",
                        "execution_allowed": True,
                    },
                ), patch(
                    "bot.trading_state_machine._live_activation_gate",
                    return_value=(True, ""),
                ), patch(
                    "bot.trading_state_machine._capital_readiness_gate",
                    return_value=(True, "ok"),
                ), patch(
                    "bot.trading_state_machine._nonce_writer_lease_gate",
                    return_value=(True, ""),
                ), patch(
                    "bot.trading_state_machine._runtime_writer_nonce_ready",
                    return_value=(True, ""),
                ):
                    self.assertIsInstance(sm.commit_activation(), bool)

    def test_commit_activation_blocks_on_malformed_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "heartbeat_verified.flag")
            with open(marker_path, "w", encoding="utf-8") as marker_file:
                marker_file.write("{not-json")
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_MAX_AGE_SECONDS": "3600",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertFalse(sm.commit_activation())

    def test_commit_activation_blocks_when_required_stage_not_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "order-verify-heartbeat.flag")
            with open(marker_path, "w", encoding="utf-8") as marker_file:
                marker_file.write(
                    json.dumps(
                        {
                            "verified": True,
                            "version": 2,
                            "stage": "ORDER_VERIFY",
                            "verified_at_epoch": time.time(),
                        }
                    )
                )
            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_REQUIRED_STAGE": "FILL_VERIFY",
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertFalse(sm.commit_activation())

    def test_commit_activation_blocks_when_legacy_marker_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            marker_path = os.path.join(tmp, "legacy-heartbeat.flag")
            with open(marker_path, "w", encoding="utf-8") as marker_file:
                marker_file.write("verified")

            with patch.dict(
                os.environ,
                {
                    "LIVE_CAPITAL_VERIFIED": "true",
                    "DRY_RUN_MODE": "false",
                    "AUTO_ACTIVATE": "true",
                    "HEARTBEAT_TRADE": "true",
                    "HEARTBEAT_MARKER_PATH": marker_path,
                },
                clear=False,
            ):
                sm = TradingStateMachine(state_file=state_path)
                self.assertFalse(sm.commit_activation())


if __name__ == "__main__":
    unittest.main()
