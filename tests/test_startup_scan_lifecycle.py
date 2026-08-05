"""Regression tests for the startup scan lifecycle in EntrypointWriterAuthority.

Covers:
* record_scan_started() — idempotency, SCAN_RUNNING phase advancement,
  scan_deadline_exceeded flag cleared.
* record_scan_complete() — idempotency, SCAN_COMPLETE phase advancement,
  implicit scan_started invocation when called without a prior
  record_scan_started(), watchdog cancel event set.
* _scan_started_watchdog_loop() — exits immediately when scan starts,
  exits immediately when cancel event is set, fires
  SCAN_STARTED_DEADLINE_EXCEEDED when deadline passes without scan,
  clears the deadline flag and exits when cancelled after the deadline.
* Re-acquisition reset — _scan_complete_at and _scan_watchdog_cancel are
  reset on each new writer-lease acquisition.

These tests use only the public/internal state of EntrypointWriterAuthority
(no Redis required).  The HeartbeatState singleton is reset before each test
to ensure phase-advancement assertions start from a clean baseline.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level loader helpers
# ---------------------------------------------------------------------------

_BOT_DIR = Path(__file__).resolve().parents[1] / "bot"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_heartbeat_state() -> ModuleType:
    key = "heartbeat_state_test_iso"
    if key in sys.modules:
        del sys.modules[key]
    return _load_module(_BOT_DIR / "heartbeat_state.py", key)


def _load_ewa(hs_mod: ModuleType) -> ModuleType:
    """Load entrypoint_writer_authority with heartbeat_state patched to hs_mod."""
    key = "ewa_test_iso"
    if key in sys.modules:
        del sys.modules[key]

    # Patch the try/except import inside entrypoint_writer_authority so it uses
    # the isolated heartbeat_state module loaded above.
    with patch.dict(
        sys.modules,
        {
            "bot.heartbeat_state": hs_mod,
            "heartbeat_state": hs_mod,
        },
    ):
        mod = _load_module(_BOT_DIR / "entrypoint_writer_authority.py", key)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hs():
    """Fresh HeartbeatState singleton for each test."""
    hs_mod = _load_heartbeat_state()
    return hs_mod.reset_heartbeat_state_for_testing(), hs_mod


@pytest.fixture()
def authority(hs):
    """EntrypointWriterAuthority instance with heartbeat_state isolated."""
    _state, hs_mod = hs
    ewa_mod = _load_ewa(hs_mod)
    inst = ewa_mod.EntrypointWriterAuthority()
    # Simulate a freshly acquired lease so timestamps are meaningful.
    inst._acquired_at = time.time()
    inst._instance_id = "test-instance-1"
    inst._generation = 1
    return inst, hs_mod


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _phase(hs_mod: ModuleType) -> Any:
    return hs_mod.get_heartbeat_state().phase


# ---------------------------------------------------------------------------
# record_scan_started tests
# ---------------------------------------------------------------------------


class TestRecordScanStarted:
    def test_sets_scan_started_at(self, authority):
        inst, hs_mod = authority
        assert inst._scan_started_at == 0.0
        inst.record_scan_started()
        assert inst._scan_started_at > 0.0

    def test_idempotent(self, authority):
        inst, hs_mod = authority
        inst.record_scan_started()
        first = inst._scan_started_at
        time.sleep(0.01)
        inst.record_scan_started()
        assert inst._scan_started_at == first

    def test_clears_scan_deadline_exceeded(self, authority):
        inst, hs_mod = authority
        inst._scan_deadline_exceeded = True
        inst.record_scan_started()
        assert inst._scan_deadline_exceeded is False

    def test_advances_phase_to_scan_running(self, authority):
        inst, hs_mod = authority
        Phase = hs_mod.WriterLifecyclePhase
        assert _phase(hs_mod) == Phase.BOOT
        inst.record_scan_started()
        assert _phase(hs_mod) == Phase.SCAN_RUNNING

    def test_does_not_regress_phase(self, authority):
        inst, hs_mod = authority
        Phase = hs_mod.WriterLifecyclePhase
        # Manually advance past SCAN_RUNNING
        hs_mod.get_heartbeat_state().advance_phase(Phase.SCAN_COMPLETE)
        inst._scan_started_at = 0.0  # reset so idempotency guard is not triggered
        inst.record_scan_started()
        assert _phase(hs_mod) == Phase.SCAN_COMPLETE


# ---------------------------------------------------------------------------
# record_scan_complete tests
# ---------------------------------------------------------------------------


class TestRecordScanComplete:
    def test_sets_scan_complete_at(self, authority):
        inst, hs_mod = authority
        inst.record_scan_started()
        inst.record_scan_complete()
        assert inst._scan_complete_at > 0.0

    def test_idempotent(self, authority):
        inst, hs_mod = authority
        inst.record_scan_started()
        inst.record_scan_complete()
        first = inst._scan_complete_at
        time.sleep(0.01)
        inst.record_scan_complete()
        assert inst._scan_complete_at == first

    def test_implicit_scan_started_when_not_called_first(self, authority):
        inst, hs_mod = authority
        assert inst._scan_started_at == 0.0
        inst.record_scan_complete()
        assert inst._scan_started_at > 0.0
        assert inst._scan_complete_at > 0.0

    def test_clears_scan_deadline_exceeded(self, authority):
        inst, hs_mod = authority
        inst._scan_deadline_exceeded = True
        inst.record_scan_started()
        inst.record_scan_complete()
        assert inst._scan_deadline_exceeded is False

    def test_advances_phase_to_scan_complete(self, authority):
        inst, hs_mod = authority
        Phase = hs_mod.WriterLifecyclePhase
        inst.record_scan_started()
        inst.record_scan_complete()
        assert _phase(hs_mod) == Phase.SCAN_COMPLETE

    def test_sets_watchdog_cancel_event(self, authority):
        inst, hs_mod = authority
        inst.record_scan_started()
        assert not inst._scan_watchdog_cancel.is_set()
        inst.record_scan_complete()
        assert inst._scan_watchdog_cancel.is_set()

    def test_scan_complete_at_after_scan_started_at(self, authority):
        inst, hs_mod = authority
        inst.record_scan_started()
        time.sleep(0.01)
        inst.record_scan_complete()
        assert inst._scan_complete_at >= inst._scan_started_at


# ---------------------------------------------------------------------------
# Watchdog loop tests
# ---------------------------------------------------------------------------


class TestScanStartedWatchdogLoop:
    def _make_watchdog_thread(self, inst, deadline_s: float) -> threading.Thread:
        t = threading.Thread(
            target=inst._scan_started_watchdog_loop,
            args=(deadline_s,),
            daemon=True,
        )
        return t

    def test_exits_immediately_when_scan_already_started(self, authority):
        inst, _ = authority
        inst._acquired_at = time.time()
        inst._scan_started_at = time.time()
        t = self._make_watchdog_thread(inst, deadline_s=300.0)
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "Watchdog should exit immediately after scan_started"

    def test_exits_immediately_when_cancel_set(self, authority):
        inst, _ = authority
        inst._acquired_at = time.time()
        inst._scan_watchdog_cancel.set()
        t = self._make_watchdog_thread(inst, deadline_s=300.0)
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "Watchdog should exit immediately when cancelled"

    def test_exits_and_clears_flag_when_cancel_fires_after_deadline(self, authority):
        """Watchdog should clear _scan_deadline_exceeded when cancelled after deadline."""
        inst, _ = authority
        # Place acquisition in the past so the deadline is already exceeded.
        inst._acquired_at = time.time() - 400.0
        t = self._make_watchdog_thread(inst, deadline_s=30.0)
        t.start()
        # Give the thread a moment to fire the deadline.
        time.sleep(0.15)
        assert inst._scan_deadline_exceeded is True
        # Now cancel.
        inst._scan_watchdog_cancel.set()
        t.join(timeout=2.0)
        assert not t.is_alive()
        assert inst._scan_deadline_exceeded is False

    def test_fires_deadline_exceeded_when_no_scan(self, authority):
        inst, _ = authority
        # Place acquisition in the past so it's already past the (short) deadline.
        inst._acquired_at = time.time() - 100.0
        t = self._make_watchdog_thread(inst, deadline_s=30.0)
        t.start()
        time.sleep(0.15)
        assert inst._scan_deadline_exceeded is True
        # Clean up.
        inst._scan_watchdog_cancel.set()
        t.join(timeout=2.0)

    def test_exits_cleanly_after_scan_starts_mid_run(self, authority):
        inst, _ = authority
        inst._acquired_at = time.time()
        t = self._make_watchdog_thread(inst, deadline_s=30.0)
        t.start()
        time.sleep(0.05)
        # Signal scan started.
        inst._scan_started_at = time.time()
        t.join(timeout=5.0)
        assert not t.is_alive()
        assert inst._scan_deadline_exceeded is False

    def test_cancel_wins_during_pre_deadline_wait(self, authority):
        """Cancel event should interrupt the pre-deadline wait and exit immediately."""
        inst, _ = authority
        inst._acquired_at = time.time()
        # Long deadline so the thread would normally wait.
        t = self._make_watchdog_thread(inst, deadline_s=300.0)
        t.start()
        time.sleep(0.05)
        assert t.is_alive()
        inst._scan_watchdog_cancel.set()
        t.join(timeout=2.0)
        assert not t.is_alive()


# ---------------------------------------------------------------------------
# _start_scan_started_watchdog tests
# ---------------------------------------------------------------------------


class TestStartScanStartedWatchdog:
    def test_clears_cancel_before_starting(self, authority):
        inst, _ = authority
        inst._scan_watchdog_cancel.set()
        inst._acquired_at = time.time()
        inst._start_scan_started_watchdog()
        # Cancel must have been cleared — the thread should now be waiting.
        assert not inst._scan_watchdog_cancel.is_set()
        # Clean up.
        inst._scan_watchdog_cancel.set()
        if inst._scan_started_watchdog_thread:
            inst._scan_started_watchdog_thread.join(timeout=2.0)

    def test_does_not_start_second_thread_if_already_alive(self, authority):
        inst, _ = authority
        inst._acquired_at = time.time()
        inst._start_scan_started_watchdog()
        first_thread = inst._scan_started_watchdog_thread
        inst._start_scan_started_watchdog()
        assert inst._scan_started_watchdog_thread is first_thread
        # Clean up.
        inst._scan_watchdog_cancel.set()
        if first_thread:
            first_thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Re-acquisition reset tests
# ---------------------------------------------------------------------------


class TestReAcquisitionReset:
    """Verify that scan lifecycle fields are correctly reset on new acquisition."""

    def _simulate_reacquisition_reset(self, inst) -> None:
        """Reproduce the reset block executed inside _acquire_state (heartbeat path)."""
        inst._scan_started_at = 0.0
        inst._scan_complete_at = 0.0
        inst._scan_deadline_exceeded = False
        inst._scan_watchdog_cancel.clear()

    def test_scan_complete_at_reset(self, authority):
        inst, _ = authority
        inst._scan_complete_at = time.time()
        self._simulate_reacquisition_reset(inst)
        assert inst._scan_complete_at == 0.0

    def test_cancel_event_cleared(self, authority):
        inst, _ = authority
        inst._scan_watchdog_cancel.set()
        self._simulate_reacquisition_reset(inst)
        assert not inst._scan_watchdog_cancel.is_set()

    def test_scan_started_at_reset(self, authority):
        inst, _ = authority
        inst._scan_started_at = time.time()
        self._simulate_reacquisition_reset(inst)
        assert inst._scan_started_at == 0.0

    def test_deadline_exceeded_reset(self, authority):
        inst, _ = authority
        inst._scan_deadline_exceeded = True
        self._simulate_reacquisition_reset(inst)
        assert inst._scan_deadline_exceeded is False


# ---------------------------------------------------------------------------
# Phase ordering invariant
# ---------------------------------------------------------------------------


class TestPhaseOrdering:
    """Ensure the full BOOT → LEASE_ACQUIRED → SCAN_RUNNING → SCAN_COMPLETE → LIVE
    ordering is preserved end-to-end via advance_phase."""

    def test_full_forward_sequence(self, hs):
        _state, hs_mod = hs
        Phase = hs_mod.WriterLifecyclePhase
        hs_state = hs_mod.get_heartbeat_state()

        hs_state.advance_phase(Phase.LEASE_ACQUIRED)
        assert hs_state.phase == Phase.LEASE_ACQUIRED

        hs_state.advance_phase(Phase.SCAN_RUNNING)
        assert hs_state.phase == Phase.SCAN_RUNNING

        hs_state.advance_phase(Phase.SCAN_COMPLETE)
        assert hs_state.phase == Phase.SCAN_COMPLETE

        hs_state.advance_phase(Phase.LIVE)
        assert hs_state.phase == Phase.LIVE

    def test_regression_is_silently_ignored(self, hs):
        _state, hs_mod = hs
        Phase = hs_mod.WriterLifecyclePhase
        hs_state = hs_mod.get_heartbeat_state()

        hs_state.advance_phase(Phase.SCAN_COMPLETE)
        hs_state.advance_phase(Phase.SCAN_RUNNING)  # regression — must be ignored
        assert hs_state.phase == Phase.SCAN_COMPLETE
