"""Tests for canonical runtime authority reporting in health status."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bot import readiness_table
from bot.health_check import HealthCheckManager
from bot.startup_coordinator import RuntimeAuthorityState, get_startup_coordinator


class TestHealthRuntimeAuthority(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def _mark_all_readiness(self) -> None:
        for key in readiness_table.KEYS:
            readiness_table.mark_ready(key)

    def test_detailed_status_exposes_runtime_authority(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=125.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)
        self.coordinator.record_activation_requested(requested=True, source="health-test")

        manager = HealthCheckManager()
        manager.mark_configuration_valid()
        manager.update_exchange_status(connected=1, expected=1)

        class _DummyStateMachine:
            def get_current_state(self):
                class _State:
                    value = "OFF"

                return _State()

            def can_dispatch_trades(self) -> bool:
                return False

        with patch(
            "bot.trading_state_machine.get_state_machine",
            return_value=_DummyStateMachine(),
        ):
            status = manager.get_detailed_status()
        runtime_authority = status["operational_state"]["runtime_authority"]

        self.assertEqual(runtime_authority["state"], RuntimeAuthorityState.AUTHORIZED.value)
        self.assertEqual(runtime_authority["lifecycle_phase"], "WARM")
        self.assertTrue(runtime_authority["trading_authority"])
        self.assertFalse(runtime_authority["execution_permitted"])
        self.assertEqual(
            runtime_authority["coordinator_state"],
            self.coordinator.get_state(),
        )


if __name__ == "__main__":
    unittest.main()
