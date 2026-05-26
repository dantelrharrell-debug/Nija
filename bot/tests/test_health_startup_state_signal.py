"""Tests for explicit startup state signal separation in health status."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bot import readiness_table
from bot.health_check import HealthCheckManager
from bot.startup_coordinator import get_startup_coordinator


class TestHealthStartupStateSignal(unittest.TestCase):
    def setUp(self) -> None:
        HealthCheckManager._instance = None
        get_startup_coordinator().reset_for_testing()
        readiness_table.reset()
        self.manager = HealthCheckManager()
        self.manager.state.is_alive = True
        self.manager.mark_configuration_valid()
        self.manager.update_exchange_status(connected=1, expected=1)

    def tearDown(self) -> None:
        get_startup_coordinator().reset_for_testing()
        readiness_table.reset()

    def _mark_all_readiness(self) -> None:
        for key in readiness_table.KEYS:
            readiness_table.mark_ready(key)

    def test_readiness_includes_blocked_trading_authority_signal(self) -> None:
        status, http_code = self.manager.get_readiness_status()
        self.assertEqual(http_code, 200)
        self.assertIn("startup_state", status)
        startup_state = status["startup_state"]
        self.assertEqual(startup_state["liveness"]["state"], "ALIVE")
        self.assertEqual(startup_state["readiness"]["state"], "READY")
        self.assertEqual(startup_state["trading_authority"]["state"], "BLOCKED")
        self.assertIn("ALIVE_READY_TRADING_BLOCKED", startup_state["state_code"])

    def test_readiness_reports_authorized_after_dispatch_commit(self) -> None:
        coord = get_startup_coordinator()
        self._mark_all_readiness()
        coord.record_bootstrap_state("RUNNING_SUPERVISED")
        coord.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=False,
        )
        coord.record_threads_launched(1)
        coord.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        coord.record_authority(ready=True, status={"ok": True})
        coord.record_nonce_status(ready=True)
        coord.record_dispatch_health(ready=True)
        coord.record_activation_requested(requested=True, source="unit-test")
        snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        decision = coord.evaluate_activation(snap)
        self.assertTrue(decision.allowed)
        coord.finalize_activation_commit(snap)

        class _LiveStateMachine:
            def get_current_state(self):
                class _State:
                    value = "LIVE_ACTIVE"

                return _State()

            def get_activation_committed(self) -> bool:
                return True

        with patch("bot.trading_state_machine.get_state_machine", return_value=_LiveStateMachine()):
            status, http_code = self.manager.get_readiness_status()
        self.assertEqual(http_code, 200)
        startup_state = status["startup_state"]
        self.assertEqual(startup_state["trading_authority"]["state"], "AUTHORIZED")
        self.assertEqual(startup_state["state_code"], "TRADING_AUTHORIZED")

    def test_readiness_reports_fsm_activation_completion_blocker_in_warm_phase(self) -> None:
        coord = get_startup_coordinator()
        self._mark_all_readiness()
        coord.record_bootstrap_state("RUNNING_SUPERVISED")
        coord.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=False,
        )
        coord.record_threads_launched(1)
        coord.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        coord.record_authority(ready=True, status={"ok": True})
        coord.record_nonce_status(ready=True)
        coord.record_dispatch_health(ready=True)
        coord.record_activation_requested(requested=True, source="unit-test")

        status, http_code = self.manager.get_readiness_status()
        self.assertEqual(http_code, 200)
        startup_state = status["startup_state"]
        self.assertEqual(startup_state["trading_authority"]["state"], "BLOCKED")
        self.assertEqual(
            startup_state["trading_authority"]["reason"],
            "fsm.activation_completion",
        )
        self.assertFalse(startup_state["trading_authority"]["dispatch_enabled"])
        self.assertEqual(startup_state["trading_authority"]["lifecycle_phase"], "WARM")


if __name__ == "__main__":
    unittest.main()
