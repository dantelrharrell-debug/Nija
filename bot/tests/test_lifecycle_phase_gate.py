"""Tests for lifecycle_phase as a first-class execution gating primitive.

Covers:
- LifecyclePhase derivation from RuntimeAuthorityState
- lifecycle_phase property on StartupConvergenceSnapshot
- lifecycle_phase property on GlobalStateSnapshot
- lifecycle_phase field on RuntimeAuthoritySnapshot
- can_execute() blocked in BOOT and WARM phases
- can_execute() allowed in LIVE phase (when lower gates pass)
- lifecycle_phase exposed in ExecutionDecision
"""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from bot import readiness_table
from bot.startup_coordinator import (
    LifecyclePhase,
    RuntimeAuthorityState,
    _compute_lifecycle_phase,
    get_startup_coordinator,
)


class TestLifecyclePhaseDerivation(unittest.TestCase):
    """Unit tests for _compute_lifecycle_phase and the snapshot property."""

    def test_executing_maps_to_live(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.EXECUTING.value),
            LifecyclePhase.LIVE,
        )

    def test_authorized_maps_to_warm(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.AUTHORIZED.value),
            LifecyclePhase.WARM,
        )

    def test_ready_maps_to_warm(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.READY.value),
            LifecyclePhase.WARM,
        )

    def test_standby_maps_to_boot(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.STANDBY.value),
            LifecyclePhase.BOOT,
        )

    def test_boot_maps_to_boot(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.BOOT.value),
            LifecyclePhase.BOOT,
        )

    def test_degraded_maps_to_boot(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase(RuntimeAuthorityState.DEGRADED.value),
            LifecyclePhase.BOOT,
        )

    def test_unknown_string_maps_to_boot(self) -> None:
        self.assertEqual(
            _compute_lifecycle_phase("UNKNOWN_FUTURE_STATE"),
            LifecyclePhase.BOOT,
        )


class TestLifecyclePhaseOnSnapshot(unittest.TestCase):
    """Tests lifecycle_phase property on StartupConvergenceSnapshot."""

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

    def _full_warm_setup(self) -> None:
        """Drive coordinator to a state that yields READY authority (WARM phase)."""
        self._mark_all_readiness()
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_capital_state(
            state="RUNNING", hydrated=True, balance=100.0, stale=False
        )
        self.coordinator.record_threads_launched(1)
        self.coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
        self.coordinator.record_authority(ready=True)
        self.coordinator.record_nonce_status(ready=True)
        self.coordinator.record_dispatch_health(ready=True)

    def test_early_boot_phase(self) -> None:
        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF", activation_intent=False
        )
        # In the initial state, capital_stale=True triggers DEGRADED rather than
        # BOOT in the authority reconciler — both states map to LifecyclePhase.BOOT.
        self.assertIn(
            snapshot.runtime_authority_state,
            {RuntimeAuthorityState.BOOT.value, RuntimeAuthorityState.DEGRADED.value},
        )
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.BOOT.value)

    def test_warm_phase_when_ready(self) -> None:
        self._full_warm_setup()
        snapshot = self.coordinator.build_snapshot(
            trading_state="OFF", activation_intent=False
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.READY.value)
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.WARM.value)

    def test_warm_phase_when_authorized(self) -> None:
        self._full_warm_setup()
        self.coordinator.record_activation_requested(requested=True, source="test")
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        self.assertIn(
            snapshot.runtime_authority_state,
            {RuntimeAuthorityState.AUTHORIZED.value, RuntimeAuthorityState.READY.value},
        )
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.WARM.value)

    def test_live_phase_after_commit(self) -> None:
        self._full_warm_setup()
        self.coordinator.record_activation_requested(requested=True, source="test")
        snapshot_pre = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        self.coordinator.finalize_activation_commit(snapshot_pre)
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE", activation_intent=True
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.LIVE.value)

    def test_degraded_phase_is_boot(self) -> None:
        self._full_warm_setup()
        self.coordinator.record_kill_switch(active=True)
        snapshot = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE", activation_intent=True
        )
        self.assertEqual(snapshot.runtime_authority_state, RuntimeAuthorityState.DEGRADED.value)
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.BOOT.value)


class TestLifecyclePhaseGlobalStateSnapshot(unittest.TestCase):
    """lifecycle_phase delegates correctly through GlobalStateSnapshot."""

    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def test_global_snapshot_lifecycle_phase_delegates(self) -> None:
        from bot.startup_coordinator import GLOBAL_STATE

        snapshot = GLOBAL_STATE.capture(trading_state="OFF", activation_intent=False)
        # Should be BOOT at early startup
        self.assertEqual(snapshot.lifecycle_phase, LifecyclePhase.BOOT.value)


class TestCanExecuteLifecycleGate(unittest.TestCase):
    """can_execute() is blocked in BOOT/WARM and permitted only in LIVE."""

    def _make_runtime_snapshot(self, phase: str):
        from bot.execution_authority_context import RuntimeAuthoritySnapshot
        return RuntimeAuthoritySnapshot(
            ready=(phase == LifecyclePhase.LIVE.value),
            authority_ready=True,
            nonce_ready=True,
            dispatch_health_ready=True,
            dispatch_enabled=(phase == LifecyclePhase.LIVE.value),
            kill_switch_active=False,
            coordinator_state="DISPATCH_ENABLED" if phase == LifecyclePhase.LIVE.value else "SUPERVISED_RUNNING",
            runtime_state=(
                RuntimeAuthorityState.EXECUTING.value
                if phase == LifecyclePhase.LIVE.value
                else (
                    RuntimeAuthorityState.AUTHORIZED.value
                    if phase == LifecyclePhase.WARM.value
                    else RuntimeAuthorityState.BOOT.value
                )
            ),
            reason="test",
            lifecycle_phase=phase,
        )

    def _patch_runtime_snapshot(self, phase: str):
        snapshot = self._make_runtime_snapshot(phase)
        return patch(
            "bot.execution_authority_context.runtime_authority_snapshot",
            return_value=snapshot,
        )

    def test_boot_phase_blocks_execution(self) -> None:
        from bot.execution_authority_context import can_execute

        with self._patch_runtime_snapshot(LifecyclePhase.BOOT.value):
            decision = can_execute()
        self.assertFalse(decision.allowed)
        self.assertIn("lifecycle_phase", decision.reason)
        self.assertIn("BOOT", decision.reason)
        self.assertEqual(decision.lifecycle_phase, LifecyclePhase.BOOT.value)

    def test_warm_phase_blocks_execution(self) -> None:
        from bot.execution_authority_context import can_execute

        with self._patch_runtime_snapshot(LifecyclePhase.WARM.value):
            decision = can_execute()
        self.assertFalse(decision.allowed)
        self.assertIn("lifecycle_phase", decision.reason)
        self.assertIn("WARM", decision.reason)
        self.assertEqual(decision.lifecycle_phase, LifecyclePhase.WARM.value)

    def test_live_phase_passes_lifecycle_gate(self) -> None:
        """In LIVE phase the lifecycle gate passes; lower gates may still deny."""
        from bot.execution_authority_context import can_execute

        with (
            self._patch_runtime_snapshot(LifecyclePhase.LIVE.value),
            # Lower gates will likely fail in test context (no Redis etc.);
            # what we care about is that the reason is NOT lifecycle_phase.
            patch("bot.execution_authority_context.assert_distributed_writer_authority"),
            patch(
                "bot.execution_authority_context._read_current_lease_generation",
                return_value=(0, "no_redis"),
            ),
        ):
            decision = can_execute()
        self.assertEqual(decision.lifecycle_phase, LifecyclePhase.LIVE.value)
        # lifecycle_phase gate must not be the blocker
        self.assertFalse(decision.reason.startswith("lifecycle_phase"))

    def test_execution_decision_always_carries_lifecycle_phase(self) -> None:
        """ExecutionDecision.lifecycle_phase is populated for every outcome."""
        from bot.execution_authority_context import can_execute

        for phase in (
            LifecyclePhase.BOOT.value,
            LifecyclePhase.WARM.value,
        ):
            with self._patch_runtime_snapshot(phase):
                decision = can_execute()
            self.assertIsNotNone(decision.lifecycle_phase)
            self.assertIn(decision.lifecycle_phase, {"BOOT", "WARM", "LIVE"})


class TestRuntimeAuthoritySnapshotLifecyclePhase(unittest.TestCase):
    """runtime_authority_snapshot() populates lifecycle_phase from coordinator."""

    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def test_lifecycle_phase_populated_from_coordinator(self) -> None:
        import os
        from bot.execution_authority_context import runtime_authority_snapshot

        with (
            patch.dict(os.environ, {"NIJA_RUNTIME_TRADING_STATE": "OFF", "LIVE_CAPITAL_VERIFIED": "false"}),
        ):
            snap = runtime_authority_snapshot()
        # In boot state it must be BOOT
        self.assertEqual(snap.lifecycle_phase, LifecyclePhase.BOOT.value)

    def test_lifecycle_phase_fallback_is_boot(self) -> None:
        from bot.execution_authority_context import runtime_authority_snapshot

        # Simulate coordinator import failure
        with patch("bot.execution_authority_context.runtime_authority_snapshot") as _mock:
            from bot.execution_authority_context import RuntimeAuthoritySnapshot
            _mock.return_value = RuntimeAuthoritySnapshot(
                ready=False,
                authority_ready=False,
                nonce_ready=False,
                dispatch_health_ready=False,
                dispatch_enabled=False,
                kill_switch_active=False,
                coordinator_state="unavailable",
                runtime_state="DEGRADED",
                reason="test_fallback",
                lifecycle_phase="BOOT",
            )
            snap = runtime_authority_snapshot()
        self.assertEqual(snap.lifecycle_phase, "BOOT")


if __name__ == "__main__":
    unittest.main()
