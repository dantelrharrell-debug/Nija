"""Regression tests: LIVE_PENDING_CONFIRMATION → LIVE_ACTIVE with all brokers connected.

Covers the authority deadlock described in the runtime investigation:

  Problem:
    TradingStateMachine remains in LIVE_PENDING_CONFIRMATION indefinitely
    because:
      1. authority_ready is never set to True in the readiness table.
         The authority heartbeat was not marking it; no Redis path active.
      2. capital.not_stale gate fails in the coordinator's system_readiness_proof
         because the TTL check (90 s) is stricter than the capital readiness
         gate's default TTL, even when capital was freshly validated.

  Fix:
    1. authority_heartbeat._tick() now calls readiness_table.mark_ready(
       "authority_ready") on every successful heartbeat.  For Coinbase-only
       deployments it also marks nonce_ready.
    2. _is_authority_ready() bootstraps authority_ready from the writer
       authority gate when the readiness table still says False.
    3. _commit_activation_unlocked() passes capital_stale=False to the
       coordinator when _cap_ready=True (gate already validated freshness).

Success criteria from the problem statement — after startup the logs must
contain (in order):

    BROKER_INDEPENDENT_EXECUTION_READY
    AUTHORITY_GRANTED
    LIVE_ACTIVE
    SCAN_STARTED
    SIGNAL_EVALUATION_STARTED
    ENTRY_EVALUATION_STARTED
"""

from __future__ import annotations

import os
import time
import threading
import unittest
from unittest.mock import patch

from bot.startup_coordinator import (
    RuntimeAuthorityState,
    StartupConvergenceSnapshot,
    get_startup_coordinator,
)
import bot.readiness_table as readiness_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_env(*keys: str) -> None:
    for k in keys:
        os.environ.pop(k, None)


def _make_snapshot(**overrides) -> StartupConvergenceSnapshot:
    """Return a fully-satisfied StartupConvergenceSnapshot with optional overrides."""
    defaults = dict(
        snapshot_version=1,
        coordinator_state="ACTIVATION_CONVERGING",
        bootstrap_state="RUNNING_SUPERVISED",
        capital_state="RUNNING",
        capital_version=1,
        readiness_version=1,
        readiness_table={k: True for k in readiness_table.KEYS},
        global_gate_ready=False,
        global_gate_detail="not_evaluated",
        capital_hydrated=True,
        capital_balance=3000.0,
        capital_stale=False,
        authority_version=1,
        global_epoch=1,
        authority_ready=True,
        authority_status={},
        nonce_version=1,
        nonce_ready=True,
        dispatch_health_version=1,
        dispatch_health_ready=True,
        threads_launched=2,
        threads_confirmed_running=True,
        trading_state="LIVE_PENDING_CONFIRMATION",
        activation_intent=True,
        activation_epoch=1,
        kill_switch_active=False,
        last_committed_snapshot_version=0,
        runtime_authority_state=RuntimeAuthorityState.AUTHORIZED.value,
        runtime_authority_reason="authority_converged",
        last_system_readiness_proof={},
        last_committed_system_readiness_proof={},
    )
    defaults.update(overrides)
    return StartupConvergenceSnapshot(**defaults)


# ---------------------------------------------------------------------------
# authority_ready bootstrap
# ---------------------------------------------------------------------------


class TestAuthorityReadyBootstrap(unittest.TestCase):
    """_is_authority_ready() bootstraps authority_ready from writer gate."""

    def setUp(self) -> None:
        readiness_table.reset()
        get_startup_coordinator().reset_for_testing()

    def tearDown(self) -> None:
        readiness_table.reset()
        _reset_env(
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
            "KRAKEN_NONCE_LEASE_REQUIRED",
        )

    def test_authority_ready_true_when_readiness_table_marked(self) -> None:
        """Returns True immediately when readiness table already says True."""
        from bot.trading_state_machine import _is_authority_ready

        readiness_table.mark_ready("authority_ready")
        self.assertTrue(_is_authority_ready())

    def test_authority_ready_false_when_writer_gate_fails(self) -> None:
        """Returns False when both readiness table and writer gate fail."""
        from bot.trading_state_machine import _is_authority_ready

        with patch(
            "bot.trading_state_machine._distributed_writer_authority_gate",
            return_value=(False, "redis_unavailable"),
        ):
            result = _is_authority_ready()

        self.assertFalse(result)

    def test_authority_ready_bootstraps_from_writer_gate(self) -> None:
        """Bootstraps authority_ready=True when writer gate passes."""
        from bot.trading_state_machine import _is_authority_ready

        with patch(
            "bot.trading_state_machine._distributed_writer_authority_gate",
            return_value=(True, ""),
        ):
            result = _is_authority_ready()

        self.assertTrue(result)
        self.assertTrue(readiness_table.snapshot().get("authority_ready", False))

    def test_authority_ready_bootstrap_marks_nonce_ready_for_coinbase_only(self) -> None:
        """Bootstrapping authority_ready also marks nonce_ready for Coinbase-only."""
        from bot.trading_state_machine import _is_authority_ready

        os.environ.pop("KRAKEN_NONCE_LEASE_REQUIRED", None)

        with patch(
            "bot.trading_state_machine._distributed_writer_authority_gate",
            return_value=(True, ""),
        ):
            result = _is_authority_ready()

        if result:
            self.assertTrue(readiness_table.snapshot().get("nonce_ready", False))


# ---------------------------------------------------------------------------
# Capital staleness gate fix
# ---------------------------------------------------------------------------


class TestCapitalStalenessGateFix(unittest.TestCase):
    """capital.not_stale passes when capital_stale=False in snapshot."""

    def setUp(self) -> None:
        get_startup_coordinator().reset_for_testing()

    def test_capital_not_stale_passes_when_capital_stale_false(self) -> None:
        """capital.not_stale gate passes when snapshot.capital_stale=False."""
        coord = get_startup_coordinator()
        snap = _make_snapshot(capital_stale=False)
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertTrue(
            proof.gate_results.get("capital.not_stale", False),
            "capital.not_stale must pass when capital_stale=False",
        )

    def test_capital_not_stale_fails_when_capital_stale_true(self) -> None:
        """capital.not_stale is the first blocking gate when capital_stale=True."""
        coord = get_startup_coordinator()
        snap = _make_snapshot(capital_stale=True)
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertFalse(proof.passed)
        self.assertEqual(proof.first_blocking_gate, "capital.not_stale")


# ---------------------------------------------------------------------------
# Full proof — all gates satisfied
# ---------------------------------------------------------------------------


class TestSystemReadinessProofAllGatesPass(unittest.TestCase):
    """Full system_readiness_proof passes when all gates are satisfied."""

    def setUp(self) -> None:
        get_startup_coordinator().reset_for_testing()

    def test_proof_passes_with_all_gates_satisfied(self) -> None:
        """evaluate_system_readiness_proof returns passed=True when all gates OK."""
        coord = get_startup_coordinator()
        snap = _make_snapshot()
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertTrue(
            proof.passed,
            f"All gates satisfied but proof failed at: {proof.first_blocking_gate}; "
            f"failed_gates={proof.failed_gates}",
        )
        self.assertEqual(proof.failed_gates, [])

    def test_proof_fails_at_authority_ready_when_false(self) -> None:
        """authority.ready is a blocking gate when authority_ready=False."""
        coord = get_startup_coordinator()
        snap = _make_snapshot(authority_ready=False)
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertFalse(proof.passed)
        self.assertIn("authority.ready", proof.failed_gates)


# ---------------------------------------------------------------------------
# Authority heartbeat marks readiness
# ---------------------------------------------------------------------------


class TestAuthorityHeartbeatMarksReadiness(unittest.TestCase):
    """authority_heartbeat._tick() marks authority_ready=True in readiness_table."""

    def setUp(self) -> None:
        readiness_table.reset()
        get_startup_coordinator().reset_for_testing()

    def tearDown(self) -> None:
        readiness_table.reset()
        _reset_env(
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
            "NIJA_WRITER_HEARTBEAT_ACTIVE",
            "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
            "KRAKEN_NONCE_LEASE_REQUIRED",
        )

    def _make_monitor(self):
        from bot.authority_heartbeat import AuthorityHeartbeatMonitor

        monitor = AuthorityHeartbeatMonitor(interval_s=60.0, timeout_s=5.0, max_failures=3)
        return monitor

    def test_tick_marks_authority_ready_on_success(self) -> None:
        """Successful _tick() marks authority_ready=True in readiness_table."""
        monitor = self._make_monitor()

        self.assertFalse(readiness_table.snapshot().get("authority_ready", False))

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ):
            monitor._tick()

        self.assertTrue(
            readiness_table.snapshot().get("authority_ready", False),
            "authority_ready must be True in readiness_table after successful _tick()",
        )

    def test_tick_marks_nonce_ready_for_coinbase_only(self) -> None:
        """Successful _tick() marks nonce_ready=True when Kraken nonce not required."""
        monitor = self._make_monitor()
        os.environ.pop("KRAKEN_NONCE_LEASE_REQUIRED", None)

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ):
            monitor._tick()

        self.assertTrue(
            readiness_table.snapshot().get("nonce_ready", False),
            "nonce_ready must be True after _tick() in Coinbase-only mode",
        )

    def test_tick_does_not_overwrite_nonce_ready_when_kraken_required(self) -> None:
        """Successful _tick() does NOT set nonce_ready when Kraken nonce is in use."""
        monitor = self._make_monitor()
        os.environ["KRAKEN_NONCE_LEASE_REQUIRED"] = "1"

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ):
            monitor._tick()

        self.assertFalse(
            readiness_table.snapshot().get("nonce_ready", False),
            "nonce_ready must NOT be auto-set when KRAKEN_NONCE_LEASE_REQUIRED is set",
        )

    def test_failed_tick_does_not_mark_authority_ready(self) -> None:
        """Failed _tick() must NOT mark authority_ready=True."""
        from bot.authority_heartbeat import AuthorityHeartbeatMonitor

        monitor = AuthorityHeartbeatMonitor(interval_s=60.0, timeout_s=5.0, max_failures=3)

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(False, "redis_unavailable"),
        ):
            monitor._tick()

        self.assertFalse(
            readiness_table.snapshot().get("authority_ready", False),
            "authority_ready must remain False after a failed _tick()",
        )


# ---------------------------------------------------------------------------
# BROKER_INDEPENDENT_EXECUTION_READY log + watchdog timestamp
# ---------------------------------------------------------------------------


class TestBrokerIndependentExecutionReadyLog(unittest.TestCase):
    """BROKER_INDEPENDENT_EXECUTION_READY is logged when all outer gates pass."""

    def setUp(self) -> None:
        import bot.trading_state_machine as tsm_mod
        tsm_mod._broker_execution_ready_at = None

    def tearDown(self) -> None:
        import bot.trading_state_machine as tsm_mod
        tsm_mod._broker_execution_ready_at = None

    def test_ready_logged_when_all_gates_pass(self) -> None:
        """commit_activation() sets _broker_execution_ready_at when all gates pass."""
        from bot.trading_state_machine import commit_activation
        import bot.trading_state_machine as tsm_mod

        self.assertIsNone(tsm_mod._broker_execution_ready_at)

        result = commit_activation(
            kill=False,
            capital_ready=True,
            execution_ready=True,
            venue_ready=True,
            live_verified=True,
            invariant=True,
            snapshot_ready=True,
        )

        self.assertTrue(result)
        self.assertIsNotNone(tsm_mod._broker_execution_ready_at)

    def test_ready_not_set_when_capital_blocks(self) -> None:
        """_broker_execution_ready_at is NOT set when capital gate fails."""
        from bot.trading_state_machine import commit_activation
        import bot.trading_state_machine as tsm_mod

        result = commit_activation(
            kill=False,
            capital_ready=False,
            execution_ready=True,
            venue_ready=True,
            live_verified=True,
            invariant=True,
            snapshot_ready=True,
        )

        self.assertFalse(result)
        self.assertIsNone(tsm_mod._broker_execution_ready_at)

    def test_timestamp_is_idempotent(self) -> None:
        """_broker_execution_ready_at is set only once across repeated calls."""
        from bot.trading_state_machine import commit_activation
        import bot.trading_state_machine as tsm_mod

        commit_activation(
            kill=False, capital_ready=True, execution_ready=True,
            venue_ready=True, live_verified=True, invariant=True, snapshot_ready=True,
        )
        t1 = tsm_mod._broker_execution_ready_at
        time.sleep(0.05)
        commit_activation(
            kill=False, capital_ready=True, execution_ready=True,
            venue_ready=True, live_verified=True, invariant=True, snapshot_ready=True,
        )
        t2 = tsm_mod._broker_execution_ready_at
        self.assertEqual(t1, t2, "Timestamp must not change on subsequent calls")


# ---------------------------------------------------------------------------
# Primary regression: LIVE_PENDING_CONFIRMATION → LIVE_ACTIVE
# ---------------------------------------------------------------------------


class TestLivePendingToLiveActiveTransition(unittest.TestCase):
    """Integration: LIVE_PENDING_CONFIRMATION → LIVE_ACTIVE with all brokers connected.

    This is the primary regression test.  With the authority_ready fix and the
    capital_stale fix applied, the coordinator's system_readiness_proof must pass
    and the state machine must be able to transition to LIVE_ACTIVE.
    """

    def setUp(self) -> None:
        readiness_table.reset()
        get_startup_coordinator().reset_for_testing()
        import bot.trading_state_machine as tsm_mod
        tsm_mod._broker_execution_ready_at = None

    def tearDown(self) -> None:
        readiness_table.reset()
        import bot.trading_state_machine as tsm_mod
        tsm_mod._broker_execution_ready_at = None
        _reset_env(
            "LIVE_CAPITAL_VERIFIED",
            "DRY_RUN_MODE",
            "PAPER_MODE",
            "NIJA_FORCE_ACTIVATION",
            "NIJA_RUNTIME_TRADING_STATE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY",
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
            "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
            "NIJA_WRITER_HEARTBEAT_ACTIVE",
            "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
            "KRAKEN_NONCE_LEASE_REQUIRED",
        )

    def test_proof_passes_after_authority_and_capital_fix(self) -> None:
        """System readiness proof passes when authority_ready=True and capital_stale=False.

        This is the core regression: fixes for authority_ready (heartbeat marks
        readiness table) and capital_stale (use _cap_ready result) must together
        allow the coordinator proof to pass.
        """
        coord = get_startup_coordinator()

        # Mark all readiness table keys True (simulates a fully started system).
        for key in readiness_table.KEYS:
            readiness_table.mark_ready(key)

        snap = _make_snapshot(
            capital_stale=False,          # Fix 2: _cap_ready=True → capital_stale=False
            authority_ready=True,         # Fix 1: heartbeat marks readiness table
            nonce_ready=True,
        )
        proof = coord.evaluate_system_readiness_proof(snap)

        self.assertTrue(
            proof.passed,
            f"System readiness proof must pass after fixes; "
            f"first_blocking_gate={proof.first_blocking_gate!r} "
            f"failed_gates={proof.failed_gates}",
        )

    def test_proof_blocked_by_capital_stale_before_fix(self) -> None:
        """Before fix: capital.not_stale blocks proof (regression baseline)."""
        coord = get_startup_coordinator()
        # Simulate pre-fix state: capital was last refreshed 2+ minutes ago.
        snap = _make_snapshot(
            capital_stale=True,
            authority_ready=True,
        )
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertFalse(proof.passed)
        self.assertEqual(proof.first_blocking_gate, "capital.not_stale")

    def test_proof_blocked_by_authority_not_ready_before_fix(self) -> None:
        """Before fix: authority.ready blocks proof when heartbeat not marking table."""
        coord = get_startup_coordinator()
        snap = _make_snapshot(
            capital_stale=False,
            authority_ready=False,       # readiness table never marked
        )
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertFalse(proof.passed)
        self.assertIn("authority.ready", proof.failed_gates)

    def test_after_heartbeat_tick_authority_and_nonce_ready(self) -> None:
        """After heartbeat tick, authority_ready and nonce_ready are True in table."""
        from bot.authority_heartbeat import AuthorityHeartbeatMonitor

        monitor = AuthorityHeartbeatMonitor(interval_s=60.0, timeout_s=5.0, max_failures=3)

        os.environ.pop("KRAKEN_NONCE_LEASE_REQUIRED", None)

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ):
            monitor._tick()

        table = readiness_table.snapshot()
        self.assertTrue(table.get("authority_ready", False))
        self.assertTrue(table.get("nonce_ready", False))

        # Now the snapshot built from this table must pass the proof.
        coord = get_startup_coordinator()
        snap = _make_snapshot(
            authority_ready=table.get("authority_ready", False),
            nonce_ready=table.get("nonce_ready", False),
            capital_stale=False,
        )
        proof = coord.evaluate_system_readiness_proof(snap)
        self.assertNotIn("authority.ready", proof.failed_gates)
        self.assertNotIn("nonce.ready", proof.failed_gates)

    def test_heartbeat_tick_triggers_immediate_convergence(self) -> None:
        """Regression: heartbeat tick must call converge_runtime_authority() immediately.

        Fix for the state transition bug: after heartbeat and lease become healthy,
        runtime_execution_authority must be asserted without waiting for the next
        periodic auto-repair cycle.  This test verifies that authority_heartbeat._tick()
        calls converge_runtime_authority("authority_heartbeat_tick") synchronously on
        every successful tick.
        """
        from bot.authority_heartbeat import AuthorityHeartbeatMonitor

        monitor = AuthorityHeartbeatMonitor(interval_s=60.0, timeout_s=5.0, max_failures=3)
        os.environ.pop("KRAKEN_NONCE_LEASE_REQUIRED", None)

        converge_calls: list[str] = []

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ), patch(
            "bot.runtime_authority_convergence_repair_patch.converge_runtime_authority",
            side_effect=lambda source: converge_calls.append(source),
        ):
            monitor._tick()

        self.assertEqual(
            len(converge_calls),
            1,
            "converge_runtime_authority must be called exactly once per successful tick; "
            f"got calls={converge_calls!r}",
        )
        self.assertEqual(
            converge_calls[0],
            "authority_heartbeat_tick",
            f"converge_runtime_authority must be called with source='authority_heartbeat_tick'; "
            f"got {converge_calls[0]!r}",
        )

    def test_heartbeat_tick_convergence_failure_does_not_raise(self) -> None:
        """Convergence errors during heartbeat tick must be swallowed, not propagated.

        The tick's primary job is checking heartbeat validity; convergence is a
        best-effort side-effect.  A failing converge_runtime_authority must never
        prevent the heartbeat tick from completing successfully.
        """
        from bot.authority_heartbeat import AuthorityHeartbeatMonitor

        monitor = AuthorityHeartbeatMonitor(interval_s=60.0, timeout_s=5.0, max_failures=3)
        os.environ.pop("KRAKEN_NONCE_LEASE_REQUIRED", None)

        with patch(
            "bot.authority_heartbeat._check_authority_once",
            return_value=(True, ""),
        ), patch(
            "bot.authority_heartbeat._write_heartbeat_marker",
        ), patch.object(
            monitor, "_write_heartbeat_to_redis", return_value=None, create=True
        ), patch(
            "bot.runtime_authority_convergence_repair_patch.converge_runtime_authority",
            side_effect=RuntimeError("simulated convergence failure"),
        ):
            # Must not raise.
            monitor._tick()

        # Heartbeat should still be considered active after a convergence failure.
        self.assertEqual(monitor.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
