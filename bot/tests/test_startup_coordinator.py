"""Tests for deterministic startup coordinator convergence."""

from __future__ import annotations

import unittest

from bot import readiness_table
from bot.startup_coordinator import (
    RuntimeAuthorityState,
    StartupCoordinatorState,
    get_startup_coordinator,
)


class TestStartupCoordinator(unittest.TestCase):
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

    def test_dispatch_enablement_retries_on_new_snapshot_version(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=250.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True, status={"ok": True})
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=False, detail="execution pipeline pending")
        self.coordinator.record_activation_requested(requested=True, source="test")

        blocked = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        blocked_decision = self.coordinator.evaluate_activation(blocked)
        self.assertFalse(blocked_decision.allowed)
        self.assertEqual(
            blocked_decision.target_state,
            StartupCoordinatorState.ACTIVATION_CONVERGING,
        )
        self.assertEqual(blocked.runtime_authority_state, RuntimeAuthorityState.READY.value)

        self.coordinator.record_dispatch_health(ready=True, detail="execution pipeline healthy")
        self.coordinator.record_activation_requested(requested=True, source="test")
        converged = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        converged_decision = self.coordinator.evaluate_activation(converged)
        self.assertTrue(converged_decision.allowed)
        self.assertGreater(converged.snapshot_version, blocked.snapshot_version)
        self.assertEqual(converged.runtime_authority_state, RuntimeAuthorityState.AUTHORIZED.value)

    def test_finalize_activation_commit_marks_dispatch_enabled(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)
        self.coordinator.record_activation_requested(requested=True, source="test")

        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        decision = self.coordinator.evaluate_activation(snapshot)
        self.assertTrue(decision.allowed)

        self.coordinator.finalize_activation_commit(snapshot)
        committed = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        self.assertTrue(committed.dispatch_enabled)
        self.assertEqual(committed.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)
        self.assertTrue(committed.execution_permitted)
        self.assertEqual(
            committed.last_committed_snapshot_version,
            snapshot.snapshot_version,
        )
        self.assertEqual(
            self.coordinator.get_state(),
            StartupCoordinatorState.DISPATCH_ENABLED.value,
        )

    def test_runtime_authority_reports_ready_without_activation_intent(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)

        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.READY.value)
        self.assertFalse(snapshot.trading_authority)
        self.assertFalse(snapshot.execution_permitted)


if __name__ == "__main__":
    unittest.main()
