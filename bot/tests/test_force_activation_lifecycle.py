"""Regression tests for the NIJA_FORCE_ACTIVATION → lifecycle_phase=LIVE path.

Covers the gap between _force_live_active_transition() in TradingStateMachine
and can_execute() in execution_authority_context:

  Before the fix:
    _force_live_active_transition() set NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
    but never called StartupCoordinator.force_activate_bypass(), so
    last_committed_snapshot_version stayed 0, dispatch_committed=False,
    executing=False, and the lifecycle gate in can_execute() returned BOOT.

  After the fix:
    force_activate_bypass() sets last_committed_snapshot_version > 0 and
    runtime_authority_state=EXECUTING.  The reconcile early-return guard
    preserves EXECUTING on subsequent build_snapshot() calls so that
    lifecycle_phase=LIVE and Gate 0 in can_execute() passes.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bot.startup_coordinator import (
    LifecyclePhase,
    RuntimeAuthorityState,
    StartupCoordinatorState,
    get_startup_coordinator,
)


class TestForceActivateBypass(unittest.TestCase):
    """Unit tests for StartupCoordinator.force_activate_bypass()."""

    def setUp(self) -> None:
        coord = get_startup_coordinator()
        coord.reset_for_testing()

    def _coord(self):
        return get_startup_coordinator()

    # ── force_activate_bypass sets EXECUTING and non-zero commit version ──

    def test_force_activate_bypass_sets_executing(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("test_reason")
        # The reconcile early-return requires NIJA_FORCE_ACTIVATION=1 to be set.
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        self.assertEqual(snap.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)

    def test_force_activate_bypass_sets_dispatch_committed(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("test_reason")
        self.assertGreater(coord._runtime.last_committed_snapshot_version, 0)

    def test_force_activate_bypass_sets_coordinator_dispatch_enabled(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("test_reason")
        self.assertEqual(
            coord._runtime.coordinator_state,
            StartupCoordinatorState.DISPATCH_ENABLED,
        )

    def test_force_activate_bypass_lifecycle_phase_is_live(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("test_reason")
        # The reconcile early-return (and thus LIVE lifecycle_phase) requires
        # NIJA_FORCE_ACTIVATION=1 to be set by the caller.
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        self.assertEqual(snap.lifecycle_phase, LifecyclePhase.LIVE.value)

    def test_force_activate_bypass_is_idempotent(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("first")
        v1 = coord._runtime.last_committed_snapshot_version
        coord.force_activate_bypass("second")
        v2 = coord._runtime.last_committed_snapshot_version
        self.assertEqual(v1, v2, "idempotent: version must not change on repeat call")

    # ── Reconcile early-return guard honours NIJA_FORCE_ACTIVATION ──────────

    def test_reconcile_returns_executing_with_force_activation_env(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("env_guard_test")
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        self.assertEqual(snap.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)
        self.assertEqual(snap.lifecycle_phase, LifecyclePhase.LIVE.value)

    def test_reconcile_not_early_exit_without_force_activation_env(self) -> None:
        """Without NIJA_FORCE_ACTIVATION, force_activate_bypass alone is NOT
        enough to preserve EXECUTING across a reconcile cycle when authority
        prerequisites (prereqs_ready, authority_converged) are absent.

        This test documents that the safety invariant holds: the env flag is
        required to activate the bypass, even if the commit version is set.
        """
        coord = self._coord()
        coord.force_activate_bypass("no_env_test")
        env = {k: v for k, v in os.environ.items() if k != "NIJA_FORCE_ACTIVATION"}
        env.pop("NIJA_FORCE_ACTIVATION", None)
        with patch.dict(os.environ, env, clear=True):
            # Invalidate edge-trigger cache to force a full reconcile.
            coord._runtime._last_reconcile_inputs = None
            snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        # Without the env var, reconcile falls through to the standard logic.
        # authority_converged is False (no Redis/prerequisites), so executing=False.
        self.assertNotEqual(snap.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)

    def test_kill_switch_overrides_force_activation_bypass(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("kill_switch_test")
        coord._runtime.kill_switch_active = True
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            coord._runtime._last_reconcile_inputs = None  # force full reconcile
            snap = coord.build_snapshot(trading_state="LIVE_ACTIVE", activation_intent=True)
        # Kill switch must prevent the force-activation early-return.
        self.assertNotEqual(snap.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)

    def test_force_bypass_not_applied_for_non_live_trading_state(self) -> None:
        coord = self._coord()
        coord.force_activate_bypass("state_guard_test")
        with patch.dict(os.environ, {"NIJA_FORCE_ACTIVATION": "1"}):
            coord._runtime._last_reconcile_inputs = None
            snap = coord.build_snapshot(trading_state="OFF", activation_intent=True)
        # Not LIVE_ACTIVE → early return must not fire.
        self.assertNotEqual(snap.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)


class TestForceActivationEndToEnd(unittest.TestCase):
    """Integration-style tests: force_activate_bypass → can_execute lifecycle gate."""

    def setUp(self) -> None:
        coord = get_startup_coordinator()
        coord.reset_for_testing()

    def tearDown(self) -> None:
        for key in (
            "NIJA_FORCE_ACTIVATION",
            "NIJA_RUNTIME_TRADING_STATE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY",
            "LIVE_CAPITAL_VERIFIED",
            "DRY_RUN_MODE",
        ):
            os.environ.pop(key, None)

    def test_lifecycle_phase_live_after_force_bypass(self) -> None:
        coord = get_startup_coordinator()
        coord.force_activate_bypass("e2e_test")
        os.environ["NIJA_FORCE_ACTIVATION"] = "1"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"

        from bot.execution_authority_context import runtime_authority_snapshot

        snap = runtime_authority_snapshot()
        self.assertEqual(
            snap.lifecycle_phase,
            LifecyclePhase.LIVE.value,
            f"Expected LIVE lifecycle phase; got {snap.lifecycle_phase!r} "
            f"(runtime_state={snap.runtime_state!r})",
        )

    def test_can_execute_gate0_passes_after_force_bypass(self) -> None:
        """After force_activate_bypass + env wiring, Gate 0 in can_execute() must
        not return lifecycle_phase:BOOT or lifecycle_phase:WARM."""
        coord = get_startup_coordinator()
        coord.force_activate_bypass("gate0_test")
        os.environ["NIJA_FORCE_ACTIVATION"] = "1"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"

        from bot.execution_authority_context import can_execute

        decision = can_execute()
        # Gate 0 should NOT be the blocking reason — lifecycle must be LIVE.
        self.assertNotIn(
            decision.lifecycle_phase,
            (LifecyclePhase.BOOT.value, LifecyclePhase.WARM.value),
            f"Gate 0 still blocking: lifecycle_phase={decision.lifecycle_phase!r}, "
            f"reason={decision.reason!r}",
        )
        self.assertEqual(
            decision.lifecycle_phase,
            LifecyclePhase.LIVE.value,
        )


if __name__ == "__main__":
    unittest.main()
