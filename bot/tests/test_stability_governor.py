"""Tests for bot/stability_governor.py — FSM transitions, hysteresis, and potential."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.stability_governor import (
    GovernorMode,
    GovernorSnapshot,
    StabilityGovernor,
    StabilityPotential,
    StabilityVector,
    get_stability_governor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_vector(**overrides) -> StabilityVector:
    """Return a fully healthy StabilityVector with optional field overrides."""
    defaults = dict(
        runtime_authority_ok=True,
        execution_permitted=True,
        global_epoch_current=True,
        lease_valid=True,
        heartbeat_fresh=True,
        nonce_ready=True,
        anomaly_pressure=0.0,
        cluster_pressure=0.0,
        dispatch_health=True,
        kill_switch_active=False,
    )
    defaults.update(overrides)
    return StabilityVector(**defaults)


def _failed_vector(**overrides) -> StabilityVector:
    """Return a fully unhealthy StabilityVector with optional field overrides."""
    defaults = dict(
        runtime_authority_ok=False,
        execution_permitted=False,
        global_epoch_current=False,
        lease_valid=False,
        heartbeat_fresh=False,
        nonce_ready=False,
        anomaly_pressure=1.0,
        cluster_pressure=1.0,
        dispatch_health=False,
        kill_switch_active=False,
    )
    defaults.update(overrides)
    return StabilityVector(**defaults)


class _IsolatedGovernor(StabilityGovernor):
    """StabilityGovernor subclass that bypasses live system calls in _gather_vector_locked."""

    def __init__(self, canned_vector: StabilityVector) -> None:
        super().__init__()
        self._canned = canned_vector

    def _gather_vector_locked(self) -> StabilityVector:
        return self._canned

    def set_vector(self, vector: StabilityVector) -> None:
        self._canned = vector


# ---------------------------------------------------------------------------
# Lyapunov potential tests
# ---------------------------------------------------------------------------

class TestStabilityPotential(unittest.TestCase):
    """Validate that V_t is computed correctly from StabilityVector inputs."""

    def setUp(self) -> None:
        self.gov = _IsolatedGovernor(_stable_vector())
        self.gov.reset_for_testing()

    def _compute(self, vector: StabilityVector) -> StabilityPotential:
        with self.gov._lock:
            return self.gov._compute_potential_locked(vector)

    def test_stable_vector_produces_zero_potential(self) -> None:
        potential = self._compute(_stable_vector())
        self.assertAlmostEqual(potential.value, 0.0, places=4)

    def test_all_failures_produce_near_maximum_potential(self) -> None:
        potential = self._compute(_failed_vector())
        self.assertGreater(potential.value, 0.85)

    def test_single_lease_failure_adds_weight(self) -> None:
        v_stable = self._compute(_stable_vector())
        # Reset prev_v to avoid delta contamination
        self.gov._prev_v = 0.0
        v_lease = self._compute(_stable_vector(lease_valid=False))
        self.assertGreater(v_lease.value, v_stable.value)

    def test_delta_positive_when_potential_worsens(self) -> None:
        self.gov._prev_v = 0.0
        self._compute(_stable_vector())           # establishes _prev_v ≈ 0
        self.gov._prev_v = 0.0
        p2 = self._compute(_stable_vector(lease_valid=False, heartbeat_fresh=False))
        self.assertGreater(p2.delta, 0.0)

    def test_delta_negative_when_potential_improves(self) -> None:
        self.gov._prev_v = 1.0
        p = self._compute(_stable_vector())
        self.assertLess(p.delta, 0.0)

    def test_anomaly_pressure_contributes_to_potential(self) -> None:
        self.gov._prev_v = 0.0
        p_no = self._compute(_stable_vector(anomaly_pressure=0.0))
        self.gov._prev_v = 0.0
        p_yes = self._compute(_stable_vector(anomaly_pressure=1.0))
        self.assertGreater(p_yes.value, p_no.value)

    def test_potential_clamped_to_0_1(self) -> None:
        for _ in range(10):
            self.gov._prev_v = 1.0
            p = self._compute(_failed_vector())
            self.assertLessEqual(p.value, 1.0)
            self.assertGreaterEqual(p.value, 0.0)


# ---------------------------------------------------------------------------
# FSM transition tests
# ---------------------------------------------------------------------------

class TestGovernorFSM(unittest.TestCase):
    """Validate deterministic FSM transitions and hysteresis."""

    def _gov(self, vector: StabilityVector) -> _IsolatedGovernor:
        g = _IsolatedGovernor(vector)
        g.reset_for_testing()
        return g

    # -- BOOT → OBSERVE --------------------------------------------------

    def test_boot_transitions_to_observe_on_first_evaluate(self) -> None:
        g = self._gov(_stable_vector())
        snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.OBSERVE)

    # -- OBSERVE → STABLE ------------------------------------------------

    def test_observe_transitions_to_stable_after_two_healthy_cycles(self) -> None:
        g = self._gov(_stable_vector())
        g.evaluate()  # BOOT → OBSERVE
        g.evaluate()  # first OBSERVE cycle (observe_cycles=1 < 2)
        snap = g.evaluate()  # second OBSERVE cycle → STABLE
        self.assertEqual(snap.mode, GovernorMode.STABLE)

    def test_observe_stays_in_observe_when_potential_too_high(self) -> None:
        g = self._gov(_failed_vector(kill_switch_active=False, lease_valid=True, nonce_ready=True))
        g.evaluate()  # BOOT → OBSERVE
        for _ in range(5):
            snap = g.evaluate()
        # V_t is high → should NOT advance past OBSERVE
        self.assertEqual(snap.mode, GovernorMode.OBSERVE)

    # -- STABLE → GUARDED ------------------------------------------------

    def test_stable_escalates_to_guarded_on_persistent_v_rise(self) -> None:
        g = self._gov(_stable_vector())
        # Warm up to STABLE
        for _ in range(3):
            g.evaluate()
        self.assertEqual(g._mode, GovernorMode.STABLE)
        # Inject rising potential without hard invariants (heartbeat+authority fail → V_t > 0.25)
        g.set_vector(_stable_vector(heartbeat_fresh=False, runtime_authority_ok=False))
        # Need NIJA_SG_RISING_TO_GUARDED=3 consecutive rises
        for _ in range(3):
            snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.GUARDED)

    def test_stable_does_not_escalate_on_single_spike(self) -> None:
        g = self._gov(_stable_vector())
        for _ in range(3):
            g.evaluate()
        self.assertEqual(g._mode, GovernorMode.STABLE)
        # One bad cycle (no hard invariant) then recover
        g.set_vector(_stable_vector(heartbeat_fresh=False, runtime_authority_ok=False))
        g.evaluate()
        g.set_vector(_stable_vector())
        snap = g.evaluate()
        # Not yet 3 consecutive rises — must still be STABLE
        self.assertEqual(snap.mode, GovernorMode.STABLE)

    # -- GUARDED → HALT --------------------------------------------------

    def test_guarded_escalates_to_halt_on_critical_potential(self) -> None:
        g = self._gov(_stable_vector())
        for _ in range(3):
            g.evaluate()
        # Force GUARDED
        with g._lock:
            g._mode = GovernorMode.GUARDED
        # Inject high-potential vector (everything broken except kill_switch)
        g.set_vector(_failed_vector(kill_switch_active=False, lease_valid=True, nonce_ready=True))
        for _ in range(3):
            snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.HALT)

    def test_kill_switch_forces_halt_from_any_state(self) -> None:
        for start_mode in (GovernorMode.STABLE, GovernorMode.GUARDED, GovernorMode.RECOVERING):
            g = self._gov(_stable_vector(kill_switch_active=True))
            with g._lock:
                g._mode = start_mode
            snap = g.evaluate()
            self.assertEqual(
                snap.mode,
                GovernorMode.HALT,
                f"Expected HALT from {start_mode.value}",
            )

    # -- HALT → RECOVERING -----------------------------------------------

    def test_halt_transitions_to_recovering_when_healthy_and_improving(self) -> None:
        g = self._gov(_stable_vector())
        with g._lock:
            g._mode = GovernorMode.HALT
            g._prev_v = 0.5  # artificially set high prev so delta goes negative
        snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.RECOVERING)

    def test_halt_stays_halted_when_hard_invariant_remains(self) -> None:
        g = self._gov(_stable_vector(kill_switch_active=True))
        with g._lock:
            g._mode = GovernorMode.HALT
            g._prev_v = 0.5
        snap = g.evaluate()
        # kill_switch_active → hard_halt → stays HALT
        self.assertEqual(snap.mode, GovernorMode.HALT)

    # -- RECOVERING → STABLE ---------------------------------------------

    def test_recovering_completes_to_stable_after_quorum(self) -> None:
        g = self._gov(_stable_vector())
        with g._lock:
            g._mode = GovernorMode.RECOVERING
            g._prev_v = 0.0
        # NIJA_SG_RECOVERY_QUORUM=5: need 5 cycles with V_t ≤ guarded_threshold.
        # _stable_vector() gives V_t≈0 so each cycle increments _recovery_window.
        for _ in range(6):
            snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.STABLE)

    def test_recovering_regresses_to_guarded_on_potential_spike(self) -> None:
        g = self._gov(_stable_vector())
        with g._lock:
            g._mode = GovernorMode.RECOVERING
            g._prev_v = 0.0
        # Use a vector that raises V_t above guarded_threshold WITHOUT triggering kill_switch
        g.set_vector(_stable_vector(heartbeat_fresh=False, runtime_authority_ok=False))
        snap = g.evaluate()
        self.assertEqual(snap.mode, GovernorMode.GUARDED)

    # -- Transition counter ----------------------------------------------

    def test_transition_count_increments_on_each_mode_change(self) -> None:
        g = self._gov(_stable_vector())
        snap0 = g.evaluate()  # BOOT → OBSERVE
        self.assertGreaterEqual(snap0.transition_count, 1)
        snap1 = g.evaluate()
        snap2 = g.evaluate()
        snap3 = g.evaluate()
        self.assertGreater(snap3.transition_count, snap0.transition_count)


# ---------------------------------------------------------------------------
# Anomaly counter tests
# ---------------------------------------------------------------------------

class TestAnomalyCounter(unittest.TestCase):
    def test_notify_anomaly_increments_kind_counts(self) -> None:
        g = get_stability_governor(reset=True)
        with patch.object(g, "_read_enabled", return_value=True):
            g.notify_anomaly("nonce_drift", "test detail")
            g.notify_anomaly("nonce_drift", "second")
            g.notify_anomaly("fencing_mismatch", "test")
        snap = g.get_snapshot()
        self.assertEqual(snap.anomaly_counts.get("nonce_drift", 0), 2)
        self.assertEqual(snap.anomaly_counts.get("fencing_mismatch", 0), 1)

    def test_notify_anomaly_noop_when_disabled(self) -> None:
        g = get_stability_governor(reset=True)
        with patch.object(g, "_read_enabled", return_value=False):
            g.notify_anomaly("nonce_drift")
        snap = g.get_snapshot()
        self.assertEqual(snap.anomaly_counts.get("nonce_drift", 0), 0)

    def test_anomaly_pressure_increases_with_events(self) -> None:
        g = get_stability_governor(reset=True)
        p_before = g._compute_anomaly_pressure_locked()
        for _ in range(5):
            g._anomaly_events.append(time.monotonic())
        p_after = g._compute_anomaly_pressure_locked()
        self.assertGreater(p_after, p_before)


# ---------------------------------------------------------------------------
# Exploration damping tests
# ---------------------------------------------------------------------------

class TestExplorationDamping(unittest.TestCase):
    def _gov_at(self, mode: GovernorMode) -> StabilityGovernor:
        g = get_stability_governor(reset=True)
        with g._lock:
            g._mode = mode
        return g

    def test_stable_returns_full_damping(self) -> None:
        self.assertAlmostEqual(self._gov_at(GovernorMode.STABLE).exploration_damping(), 1.0)

    def test_observe_returns_full_damping(self) -> None:
        self.assertAlmostEqual(self._gov_at(GovernorMode.OBSERVE).exploration_damping(), 1.0)

    def test_guarded_returns_half_damping(self) -> None:
        self.assertAlmostEqual(self._gov_at(GovernorMode.GUARDED).exploration_damping(), 0.5)

    def test_recovering_returns_partial_damping(self) -> None:
        self.assertAlmostEqual(self._gov_at(GovernorMode.RECOVERING).exploration_damping(), 0.75)

    def test_halt_returns_zero_damping(self) -> None:
        self.assertAlmostEqual(self._gov_at(GovernorMode.HALT).exploration_damping(), 0.0)


# ---------------------------------------------------------------------------
# is_halted() tests
# ---------------------------------------------------------------------------

class TestIsHalted(unittest.TestCase):
    def test_is_halted_true_in_halt_mode(self) -> None:
        g = get_stability_governor(reset=True)
        with g._lock:
            g._mode = GovernorMode.HALT
        self.assertTrue(g.is_halted())

    def test_is_halted_false_in_stable_mode(self) -> None:
        g = get_stability_governor(reset=True)
        with g._lock:
            g._mode = GovernorMode.STABLE
        self.assertFalse(g.is_halted())

    def test_is_halted_never_raises(self) -> None:
        g = get_stability_governor(reset=True)
        # Even if internal state is broken, should not raise
        try:
            result = g.is_halted()
            self.assertIsInstance(result, bool)
        except Exception as exc:
            self.fail(f"is_halted() raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):
    def test_get_stability_governor_returns_same_instance(self) -> None:
        g1 = get_stability_governor()
        g2 = get_stability_governor()
        self.assertIs(g1, g2)

    def test_reset_returns_new_instance(self) -> None:
        g1 = get_stability_governor()
        g2 = get_stability_governor(reset=True)
        self.assertIsNot(g1, g2)


if __name__ == "__main__":
    unittest.main()
