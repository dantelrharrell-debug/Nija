"""Tests for edge-trigger and dedup optimisations in StartupCoordinator,
GlobalState, and execution_authority_context.

Covers:
    Fix #2 – record_bootstrap_state() skips _publish_locked for idempotent repeats.
    Fix #1 – _reconcile_runtime_authority_locked() returns cached result when
              all inputs are unchanged (edge-trigger).
    Fix #3 – GlobalState.capture() returns the cached snapshot when the
              coordinator event-version and caller inputs are unchanged.
    Fix #4 – _emit_trade_admission_telemetry() is throttled to at most one
              emission per stage per _TELEMETRY_THROTTLE_S seconds.
    Fix #5 – runtime_authority_snapshot() uses GLOBAL_STATE.latest() as a
              fast path when the cached snapshot is fresh and trading_state
              matches the environment.
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from typing import Any, Dict
from unittest.mock import patch

from bot import readiness_table
from bot.startup_coordinator import (
    GLOBAL_STATE,
    GlobalState,
    RuntimeAuthorityState,
    StartupCoordinatorState,
    get_startup_coordinator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fully_ready_coordinator(coordinator: Any) -> None:
    """Drive the coordinator to a fully-converged AUTHORIZED state."""
    for key in readiness_table.KEYS:
        readiness_table.mark_ready(key)
    coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
    coordinator.record_capital_state(state="RUNNING", hydrated=True, balance=500.0, stale=False)
    coordinator.record_threads_launched(2)
    coordinator.record_threads_confirmed_running(bootstrap_state="RUNNING_SUPERVISED")
    coordinator.record_authority(ready=True, status={"ok": True})
    coordinator.record_nonce_status(ready=True)
    coordinator.record_dispatch_health(ready=True)
    coordinator.record_activation_requested(requested=True, source="test")


# ---------------------------------------------------------------------------
# Fix #2 — record_bootstrap_state() idempotent-publish dedup
# ---------------------------------------------------------------------------

class TestBootstrapStatePublishDedup(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def test_first_call_publishes(self) -> None:
        """Initial record_bootstrap_state call must always publish."""
        v1 = self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        history = self.coordinator.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["payload"]["bootstrap_state"], "RUNNING_SUPERVISED")
        self.assertEqual(v1, 1)

    def test_repeated_same_state_suppressed(self) -> None:
        """Subsequent calls with the same state string must NOT append history entries."""
        v1 = self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        v2 = self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        v3 = self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        # Only one history entry from the first call.
        history = self.coordinator.get_history()
        self.assertEqual(len(history), 1)
        # event_version must not have advanced.
        self.assertEqual(v2, v1)
        self.assertEqual(v3, v1)

    def test_new_state_after_repeat_publishes(self) -> None:
        """After suppressed repeats, a genuinely new state must publish."""
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        v_new = self.coordinator.record_bootstrap_state("ENV_VERIFIED")
        history = self.coordinator.get_history()
        # First publish + the new state = 2 entries.
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["payload"]["bootstrap_state"], "ENV_VERIFIED")
        self.assertEqual(v_new, 2)

    def test_coordinator_state_updated_even_on_suppressed_publish(self) -> None:
        """coordinator_state must be updated even when publish is suppressed."""
        # First call to RUNNING_SUPERVISED sets SUPERVISED_RUNNING.
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        # Simulate a transient state change.
        self.coordinator.record_bootstrap_state("ENV_VERIFIED")
        # Return to RUNNING_SUPERVISED (a repeat of the first value).
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        # The coordinator state must reflect SUPERVISED_RUNNING.
        self.assertEqual(
            self.coordinator.get_state(),
            StartupCoordinatorState.SUPERVISED_RUNNING.value,
        )

    def test_threads_confirmed_running_set_on_suppressed_publish(self) -> None:
        """threads_confirmed_running must be set even when RUNNING_SUPERVISED is suppressed."""
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        # Force a reset of threads_confirmed_running to simulate an edge case,
        # then fire the same state again (suppressed publish).
        self.coordinator._runtime.threads_confirmed_running = False
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        self.assertTrue(self.coordinator._runtime.threads_confirmed_running)

    def test_unknown_state_deduped(self) -> None:
        """Unknown (unmapped) bootstrap strings are also deduped."""
        self.coordinator.record_bootstrap_state("MYSTERY_STATE")
        self.coordinator.record_bootstrap_state("MYSTERY_STATE")
        self.coordinator.record_bootstrap_state("MYSTERY_STATE")
        self.assertEqual(len(self.coordinator.get_history()), 1)


# ---------------------------------------------------------------------------
# Fix #1 — _reconcile_runtime_authority_locked() edge-trigger cache
# ---------------------------------------------------------------------------

class TestReconcileEdgeTrigger(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def test_repeated_build_snapshot_same_inputs_returns_same_state(self) -> None:
        """Repeated build_snapshot calls with unchanged inputs yield the same authority state."""
        _fully_ready_coordinator(self.coordinator)
        snap1 = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        snap2 = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        self.assertEqual(snap1.runtime_authority_state, snap2.runtime_authority_state)
        self.assertEqual(snap1.runtime_authority_reason, snap2.runtime_authority_reason)

    def test_cache_invalidates_on_coordinator_state_change(self) -> None:
        """After a nonce-status change the reconcile must recompute."""
        _fully_ready_coordinator(self.coordinator)
        snap_auth = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        self.assertEqual(snap_auth.runtime_authority_state, RuntimeAuthorityState.AUTHORIZED.value)

        # Invalidate: revoke nonce → global_epoch changes → cache miss.
        self.coordinator.record_nonce_status(ready=False, detail="lost")
        snap_degraded = self.coordinator.build_snapshot(
            trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
        )
        self.assertNotEqual(
            snap_degraded.runtime_authority_state,
            RuntimeAuthorityState.AUTHORIZED.value,
        )

    def test_cache_invalidates_on_trading_state_change(self) -> None:
        """Different trading_state args must trigger a fresh reconcile."""
        _fully_ready_coordinator(self.coordinator)
        snap_off = self.coordinator.build_snapshot(trading_state="OFF", activation_intent=True)
        self.coordinator.finalize_activation_commit(
            self.coordinator.build_snapshot(
                trading_state="LIVE_PENDING_CONFIRMATION", activation_intent=True
            )
        )
        snap_live = self.coordinator.build_snapshot(
            trading_state="LIVE_ACTIVE", activation_intent=True
        )
        self.assertEqual(snap_live.runtime_authority_state, RuntimeAuthorityState.EXECUTING.value)
        self.assertNotEqual(snap_off.runtime_authority_state, snap_live.runtime_authority_state)

    def test_last_reconcile_inputs_stored(self) -> None:
        """_last_reconcile_inputs is populated after first build_snapshot call."""
        self.assertIsNone(self.coordinator._runtime._last_reconcile_inputs)
        _fully_ready_coordinator(self.coordinator)
        self.coordinator.build_snapshot(trading_state="OFF", activation_intent=False)
        self.assertIsNotNone(self.coordinator._runtime._last_reconcile_inputs)

    def test_reset_clears_reconcile_cache(self) -> None:
        """reset_for_testing() must clear the reconcile input cache."""
        self.coordinator.build_snapshot(trading_state="OFF", activation_intent=False)
        self.coordinator.reset_for_testing()
        self.assertIsNone(self.coordinator._runtime._last_reconcile_inputs)


# ---------------------------------------------------------------------------
# Fix #3 — GlobalState.capture() snapshot caching
# ---------------------------------------------------------------------------

class TestGlobalStateCaptureCaching(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()
        # Use a private GlobalState instance to avoid cross-test contamination.
        self.gs = GlobalState()

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()

    def test_first_capture_builds_snapshot(self) -> None:
        snap = self.gs.capture(trading_state="OFF", activation_intent=False)
        self.assertIsNotNone(snap)
        self.assertEqual(self.gs.latest(), snap)

    def test_identical_inputs_returns_cached_snapshot(self) -> None:
        snap1 = self.gs.capture(trading_state="OFF", activation_intent=False)
        snap2 = self.gs.capture(trading_state="OFF", activation_intent=False)
        # Should be the exact same object (cache hit).
        self.assertIs(snap1, snap2)

    def test_trading_state_change_rebuilds_snapshot(self) -> None:
        snap1 = self.gs.capture(trading_state="OFF", activation_intent=False)
        snap2 = self.gs.capture(trading_state="LIVE_ACTIVE", activation_intent=False)
        self.assertIsNot(snap1, snap2)
        self.assertEqual(snap2.startup.trading_state, "LIVE_ACTIVE")

    def test_activation_intent_change_rebuilds_snapshot(self) -> None:
        snap1 = self.gs.capture(trading_state="OFF", activation_intent=False)
        snap2 = self.gs.capture(trading_state="OFF", activation_intent=True)
        self.assertIsNot(snap1, snap2)

    def test_esc_state_change_rebuilds_snapshot(self) -> None:
        snap1 = self.gs.capture(trading_state="OFF", activation_intent=False, esc_state="IDLE")
        snap2 = self.gs.capture(trading_state="OFF", activation_intent=False, esc_state="PENDING")
        self.assertIsNot(snap1, snap2)

    def test_coordinator_state_change_invalidates_cache(self) -> None:
        snap1 = self.gs.capture(trading_state="OFF", activation_intent=False)
        # Mutate coordinator state via a record call → bumps event_version.
        self.coordinator.record_bootstrap_state("ENV_VERIFIED")
        snap2 = self.gs.capture(trading_state="OFF", activation_intent=False)
        self.assertIsNot(snap1, snap2)

    def test_get_event_version_exposed(self) -> None:
        """get_event_version() returns a non-negative integer."""
        v = self.coordinator.get_event_version()
        self.assertIsInstance(v, int)
        self.assertGreaterEqual(v, 0)

    def test_get_event_version_increments_on_record(self) -> None:
        v0 = self.coordinator.get_event_version()
        self.coordinator.record_bootstrap_state("ENV_VERIFIED")
        v1 = self.coordinator.get_event_version()
        self.assertGreater(v1, v0)

    def test_get_event_version_unchanged_on_suppressed_bootstrap(self) -> None:
        """Suppressed record_bootstrap_state must NOT advance event_version."""
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        v0 = self.coordinator.get_event_version()
        # Repeat — should be suppressed.
        self.coordinator.record_bootstrap_state("RUNNING_SUPERVISED")
        v1 = self.coordinator.get_event_version()
        self.assertEqual(v0, v1)


# ---------------------------------------------------------------------------
# Fix #4 — _emit_trade_admission_telemetry() throttle
# ---------------------------------------------------------------------------

class TestTelemetryThrottle(unittest.TestCase):
    def setUp(self) -> None:
        # Reset the module-level throttle state before each test.
        import bot.execution_authority_context as eac
        with eac._TELEMETRY_EMIT_LOCK:
            eac._TELEMETRY_LAST_EMIT.clear()

    def tearDown(self) -> None:
        import bot.execution_authority_context as eac
        with eac._TELEMETRY_EMIT_LOCK:
            eac._TELEMETRY_LAST_EMIT.clear()

    def test_first_call_logs(self) -> None:
        """First call for a stage must always emit a log."""
        import bot.execution_authority_context as eac
        with patch.object(eac.logger, "info") as mock_info:
            eac._emit_trade_admission_telemetry(
                reason="lifecycle_phase:BOOT",
                stage="lifecycle_gate",
            )
            self.assertTrue(mock_info.called)

    def test_rapid_repeat_suppressed(self) -> None:
        """Rapid repeat within throttle window must not re-log."""
        import bot.execution_authority_context as eac
        with patch.object(eac.logger, "info") as mock_info:
            eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
            mock_info.reset_mock()
            eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
            self.assertFalse(mock_info.called)

    def test_different_stage_not_throttled(self) -> None:
        """Different stage keys must not throttle each other."""
        import bot.execution_authority_context as eac
        with patch.object(eac.logger, "info") as mock_info:
            eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
            mock_info.reset_mock()
            eac._emit_trade_admission_telemetry(reason="x", stage="control_compiler")
            self.assertTrue(mock_info.called)

    def test_emission_after_throttle_window(self) -> None:
        """After the throttle window expires the next call must emit."""
        import bot.execution_authority_context as eac
        original_throttle = eac._TELEMETRY_THROTTLE_S
        try:
            eac._TELEMETRY_THROTTLE_S = 0.0  # disable throttle for this test
            with patch.object(eac.logger, "info") as mock_info:
                eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
                eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
                # With throttle=0 both calls should emit.
                self.assertEqual(mock_info.call_count, 2)
        finally:
            eac._TELEMETRY_THROTTLE_S = original_throttle

    def test_thread_safety(self) -> None:
        """Concurrent calls from multiple threads must not raise."""
        import bot.execution_authority_context as eac
        errors: list = []

        def _emit() -> None:
            try:
                eac._emit_trade_admission_telemetry(reason="x", stage="lifecycle_gate")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_emit) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Fix #5 — runtime_authority_snapshot() fast path via GLOBAL_STATE.latest()
# ---------------------------------------------------------------------------

class TestRuntimeAuthoritySnapshotFastPath(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = get_startup_coordinator()
        self.coordinator.reset_for_testing()
        readiness_table.reset()
        # Ensure GLOBAL_STATE cache is cleared.
        with GLOBAL_STATE._lock:
            GLOBAL_STATE._latest = None
            GLOBAL_STATE._cache_key = None

    def tearDown(self) -> None:
        self.coordinator.reset_for_testing()
        readiness_table.reset()
        with GLOBAL_STATE._lock:
            GLOBAL_STATE._latest = None
            GLOBAL_STATE._cache_key = None
        for envvar in ("NIJA_RUNTIME_TRADING_STATE", "LIVE_CAPITAL_VERIFIED",
                       "NIJA_RUNTIME_EXECUTION_AUTHORITY"):
            os.environ.pop(envvar, None)

    def test_fast_path_uses_cached_snapshot(self) -> None:
        """When GLOBAL_STATE.latest() is fresh and trading_state matches,
        runtime_authority_snapshot() should return without calling build_snapshot."""
        from bot.execution_authority_context import runtime_authority_snapshot

        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        # Prime GLOBAL_STATE with a snapshot for trading_state="OFF".
        GLOBAL_STATE.capture(trading_state="OFF", activation_intent=False)

        call_count: Dict[str, int] = {"n": 0}
        original_build = self.coordinator.build_snapshot

        # patch.object on a class replaces the unbound method; the replacement
        # receives the instance as the first positional argument.
        def counting_build(_self: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            return original_build(**kwargs)

        with patch.object(type(self.coordinator), "build_snapshot", counting_build):
            runtime_authority_snapshot()

        # build_snapshot should NOT have been called because the fast path fired.
        self.assertEqual(call_count["n"], 0)

    def test_stale_snapshot_falls_through_to_slow_path(self) -> None:
        """A snapshot older than 2.5 s must cause a fresh build_snapshot call."""
        from bot.execution_authority_context import runtime_authority_snapshot

        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        GLOBAL_STATE.capture(trading_state="OFF", activation_intent=False)

        # Backdate the snapshot_ts to simulate staleness.
        with GLOBAL_STATE._lock:
            old = GLOBAL_STATE._latest
        # Replace with a stale snapshot (snapshot_ts 10 s in the past).
        import dataclasses
        stale = dataclasses.replace(old, snapshot_ts=time.monotonic() - 10.0)
        with GLOBAL_STATE._lock:
            GLOBAL_STATE._latest = stale

        call_count: Dict[str, int] = {"n": 0}
        original_build = self.coordinator.build_snapshot

        def counting_build(_self: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            return original_build(**kwargs)

        with patch.object(type(self.coordinator), "build_snapshot", counting_build):
            runtime_authority_snapshot()

        self.assertGreater(call_count["n"], 0)

    def test_trading_state_mismatch_falls_through_to_slow_path(self) -> None:
        """If GLOBAL_STATE was built for a different trading_state the slow path fires."""
        from bot.execution_authority_context import runtime_authority_snapshot

        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
        # Prime cache with a different trading_state.
        GLOBAL_STATE.capture(trading_state="OFF", activation_intent=False)

        call_count: Dict[str, int] = {"n": 0}
        original_build = self.coordinator.build_snapshot

        def counting_build(_self: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            return original_build(**kwargs)

        with patch.object(type(self.coordinator), "build_snapshot", counting_build):
            runtime_authority_snapshot()

        self.assertGreater(call_count["n"], 0)

    def test_no_cached_snapshot_falls_through_to_slow_path(self) -> None:
        """When GLOBAL_STATE.latest() is None the slow path always fires."""
        from bot.execution_authority_context import runtime_authority_snapshot

        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"

        call_count: Dict[str, int] = {"n": 0}
        original_build = self.coordinator.build_snapshot

        def counting_build(_self: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            return original_build(**kwargs)

        with patch.object(type(self.coordinator), "build_snapshot", counting_build):
            runtime_authority_snapshot()

        self.assertGreater(call_count["n"], 0)

    def test_result_fields_populated_from_fast_path(self) -> None:
        """Fast-path result must expose all RuntimeAuthoritySnapshot fields."""
        from bot.execution_authority_context import RuntimeAuthoritySnapshot, runtime_authority_snapshot

        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        GLOBAL_STATE.capture(trading_state="OFF", activation_intent=False)

        snap = runtime_authority_snapshot()
        self.assertIsInstance(snap, RuntimeAuthoritySnapshot)
        # All fields should be present (dataclass ensures this; just check key ones).
        self.assertIsInstance(snap.lifecycle_phase, str)
        self.assertIsInstance(snap.runtime_state, str)
        self.assertIsInstance(snap.coordinator_state, str)


if __name__ == "__main__":
    unittest.main()
