"""Tests for deterministic startup coordinator convergence."""

from __future__ import annotations

import unittest
import threading
from dataclasses import replace

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

    def test_finalize_activation_commit_with_zero_snapshot_version_still_latches_dispatch(self) -> None:
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
        zero_version_snapshot = replace(snapshot, snapshot_version=0)
        self.coordinator.finalize_activation_commit(zero_version_snapshot)
        committed = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        self.assertGreater(committed.last_committed_snapshot_version, 0)
        self.assertEqual(committed.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)
        self.assertEqual(committed.lifecycle_phase, "LIVE")

    def test_finalize_activation_commit_refuses_when_system_readiness_proof_fails(self) -> None:
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
        # No activation request -> proof must fail on activation.intent_present.
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=False,
        )

        with self.assertRaisesRegex(RuntimeError, "system readiness proof failed"):
            self.coordinator.finalize_activation_commit(snapshot)

        blocked = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=False,
        )
        proof = blocked.last_committed_system_readiness_proof
        self.assertEqual(proof.get("passed"), False)
        self.assertEqual(proof.get("first_blocking_gate"), "activation.intent_present")
        self.assertEqual(blocked.last_committed_snapshot_version, 0)

    def test_system_readiness_proof_metadata_is_deterministic_across_recovery(self) -> None:
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

        ready_snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        self.coordinator.finalize_activation_commit(ready_snapshot)

        # Simulate post-live regression/recovery input; commit proof metadata must remain replayable.
        self.coordinator.record_nonce_status(ready=False, detail="nonce lease lost")
        degraded_snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        last_commit_proof = degraded_snapshot.last_committed_system_readiness_proof
        current_proof = self.coordinator.evaluate_system_readiness_proof(degraded_snapshot).as_dict()

        self.assertEqual(last_commit_proof.get("passed"), True)
        self.assertEqual(last_commit_proof.get("snapshot_version"), ready_snapshot.snapshot_version)
        self.assertEqual(last_commit_proof.get("commit_snapshot_version"), ready_snapshot.snapshot_version)
        self.assertEqual(current_proof.get("passed"), False)
        self.assertEqual(current_proof.get("first_blocking_gate"), "nonce.ready")

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
        self.assertEqual(snapshot.lifecycle_phase, "WARM")

    def test_default_snapshot_starts_in_boot_phase(self) -> None:
        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.BOOT.value)
        self.assertTrue(snapshot.runtime_authority_reason.startswith("suppressed_zone:"))
        self.assertEqual(snapshot.lifecycle_phase, "BOOT")

    def test_build_snapshot_suppressed_zone_skips_reconcile(self) -> None:
        self.assertIsNone(self.coordinator._runtime._last_reconcile_inputs)
        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.BOOT.value)
        self.assertTrue(snapshot.runtime_authority_reason.startswith("suppressed_zone:"))
        self.assertIsNone(self.coordinator._runtime._last_reconcile_inputs)

    def test_record_authority_in_capital_suppression_does_not_advance_global_epoch(self) -> None:
        self.coordinator.record_bootstrap_state("STARTUP_VALIDATED")
        self.coordinator.record_capital_state(
            state="REFRESHING",
            hydrated=False,
            balance=None,
            stale=True,
        )
        before = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.coordinator.record_authority(ready=True, status={"source": "unit-test"})
        after = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.assertEqual(before.global_epoch, 0)
        self.assertEqual(after.global_epoch, 0)
        hydration_log = self.coordinator.get_hydration_event_log()
        self.assertTrue(len(hydration_log) > 0)
        self.assertTrue(all(entry.get("zone") != "AUTHORITY_LIVE" for entry in hydration_log))

    def test_finalize_activation_commit_is_idempotent_for_same_snapshot(self) -> None:
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
        self.coordinator.record_authority(ready=True, status={"ok": True})
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)
        self.coordinator.record_activation_requested(requested=True, source="test")

        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        decision = self.coordinator.evaluate_activation(snapshot)
        self.assertTrue(decision.allowed)

        first_version = self.coordinator.finalize_activation_commit(snapshot)
        event_version_after_first = self.coordinator.get_event_version()
        second_version = self.coordinator.finalize_activation_commit(snapshot)
        self.assertEqual(first_version, event_version_after_first)
        self.assertEqual(second_version, event_version_after_first)
        self.assertEqual(self.coordinator.get_event_version(), event_version_after_first)

    def test_parallel_finalize_commit_emits_single_dispatch_enabled_phase_event(self) -> None:
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

        errors: list[str] = []

        def _commit() -> None:
            try:
                self.coordinator.finalize_activation_commit(snapshot)
            except Exception as exc:  # pragma: no cover - defensive capture
                errors.append(str(exc))

        t1 = threading.Thread(target=_commit, daemon=True)
        t2 = threading.Thread(target=_commit, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(errors, [])

        history = self.coordinator.get_history()
        dispatch_enabled_phase_events = [
            e
            for e in history
            if e.get("event") == "DISPATCH_ENABLED"
            and e.get("payload", {}).get("phase") == StartupCoordinatorState.DISPATCH_ENABLED.value
        ]
        self.assertEqual(len(dispatch_enabled_phase_events), 1)

    def test_capital_stale_is_contained_in_boot_until_convergence(self) -> None:
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=100.0,
            stale=True,
        )
        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF",
            activation_intent=False,
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.BOOT.value)
        self.assertEqual(snapshot.runtime_authority_reason, "capital_stale")
        self.assertEqual(snapshot.lifecycle_phase, "BOOT")

    def test_readiness_regression_revokes_after_global_gate_success(self) -> None:
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=250.0,
            stale=False,
        )
        self.coordinator.record_global_gate(ready=True, detail="barrier_passed")
        self.coordinator.record_readiness(
            key="capital_ready",
            value=True,
            version=1,
            table={"capital_ready": True, "strategy_ready": True},
        )
        self.coordinator.record_readiness(
            key="capital_ready",
            value=False,
            version=2,
            table={"capital_ready": False, "strategy_ready": False},
        )
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        self.assertFalse(snapshot.readiness_table.get("capital_ready"))
        self.assertFalse(snapshot.readiness_table.get("strategy_ready"))
        self.assertTrue(snapshot.global_gate_ready)

    def test_global_gate_cannot_override_canonical_readiness(self) -> None:
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=250.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=False)
        self.coordinator.record_nonce_status(ready=False)
        self.coordinator.record_dispatch_health(ready=False)
        self.coordinator.record_activation_requested(requested=True, source="test")
        self.coordinator.record_global_gate(ready=True, detail="all gates passed")
        self.coordinator.record_readiness(
            key="bootstrap_ready",
            value=False,
            version=1,
            table={"bootstrap_ready": False, "strategy_ready": False},
        )

        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        proof = self.coordinator.evaluate_system_readiness_proof(snapshot)
        self.assertFalse(proof.passed)
        self.assertEqual(proof.first_blocking_gate, "readiness.complete")
        self.assertIn("authority.ready", proof.failed_gates)
        self.assertIn("nonce.ready", proof.failed_gates)
        self.assertIn("dispatch_health.ready", proof.failed_gates)

    def test_live_state_is_revoked_when_readiness_regresses(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=300.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)
        self.coordinator.record_activation_requested(requested=True, source="test")
        self.coordinator.record_global_gate(ready=True, detail="barrier_passed")

        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        self.coordinator.finalize_activation_commit(snapshot)

        self.coordinator.record_readiness(
            key="strategy_ready",
            value=False,
            version=99,
            table={"strategy_ready": False},
        )
        committed = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        self.assertEqual(committed.runtime_authority_state, RuntimeAuthorityState.DEGRADED.value)
        self.assertEqual(committed.lifecycle_phase, "BOOT")
        self.assertFalse(committed.dispatch_enabled)
        self.assertEqual(committed.last_committed_snapshot_version, 0)

    def test_global_gate_regression_revokes_dispatch_commit(self) -> None:
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING",
            hydrated=True,
            balance=300.0,
            stale=False,
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(
            bootstrap_state="RUNNING_SUPERVISED"
        )
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)
        self.coordinator.record_global_gate(ready=True, detail="barrier_passed")
        self.coordinator.record_activation_requested(requested=True, source="test")
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION",
            activation_intent=True,
        )
        self.coordinator.finalize_activation_commit(snapshot)

        self.coordinator.record_global_gate(ready=False, detail="writer_lost")
        revoked = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )

        self.assertFalse(revoked.global_gate_ready)
        self.assertFalse(revoked.dispatch_enabled)
        self.assertEqual(revoked.last_committed_snapshot_version, 0)


if __name__ == "__main__":
    unittest.main()
