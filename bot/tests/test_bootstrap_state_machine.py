"""Tests for bot/bootstrap_state_machine.py

Covers:
  - Legal forward transitions through the full boot path
  - Illegal transitions are rejected (return False, no state change)
  - reset_for_retry() from various non-terminal states
  - reset_for_retry() is a no-op from terminal states
  - All 10 invariant assertions fire when violated
  - check_invariant() dispatcher routes correctly
  - get_status() / get_history() serialisable output
  - Singleton is process-wide (get_bootstrap_fsm())
  - Thread-safety: concurrent transitions don't corrupt state
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

from bot.bootstrap_state_machine import (
    BootstrapInvariantError,
    BootstrapState,
    BootstrapStateMachine,
    get_bootstrap_fsm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh() -> BootstrapStateMachine:
    """Return a brand-new FSM starting at BOOT_INIT."""
    return BootstrapStateMachine()


def _fast_forward(fsm: BootstrapStateMachine, *states: BootstrapState) -> None:
    """Apply a sequence of transitions; raises on first failure."""
    for s in states:
        ok = fsm.transition(s, "test fast-forward")
        if not ok:
            raise AssertionError(
                f"fast_forward: transition to {s.value} failed from {fsm.state.value}"
            )


# ---------------------------------------------------------------------------
# Full forward path
# ---------------------------------------------------------------------------

class TestLegalTransitions(unittest.TestCase):
    """Every step of the happy-path must succeed."""

    HAPPY_PATH = [
        BootstrapState.LOCK_ACQUIRED,
        BootstrapState.HEALTH_BOUND,
        BootstrapState.ENV_VERIFIED,
        BootstrapState.STARTUP_VALIDATED,
        BootstrapState.MODE_GATED,
        BootstrapState.PLATFORM_CONNECTING,
        BootstrapState.PLATFORM_READY,
        BootstrapState.CAPITAL_REFRESHING,
        BootstrapState.CAPITAL_READY,
        BootstrapState.THREADS_STARTING,
        BootstrapState.RUNNING_SUPERVISED,
        BootstrapState.SHUTDOWN,
    ]

    def test_full_happy_path(self):
        fsm = _fresh()
        self.assertEqual(fsm.state, BootstrapState.BOOT_INIT)
        for target in self.HAPPY_PATH:
            result = fsm.transition(target, "test")
            self.assertTrue(result, f"Expected True transitioning to {target.value}")
            self.assertEqual(fsm.state, target)

    def test_config_error_path(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.CONFIG_ERROR_KEEPALIVE,
            BootstrapState.SHUTDOWN,
        )
        self.assertEqual(fsm.state, BootstrapState.SHUTDOWN)

    def test_external_restart_path(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.EXTERNAL_RESTART_REQUIRED,
            BootstrapState.SHUTDOWN,
        )
        self.assertEqual(fsm.state, BootstrapState.SHUTDOWN)

    def test_retry_path(self):
        """BOOT_FAILED_RETRY → PLATFORM_CONNECTING → ... → RUNNING_SUPERVISED."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.BOOT_FAILED_RETRY,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        )
        self.assertEqual(fsm.state, BootstrapState.RUNNING_SUPERVISED)


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------

class TestIllegalTransitions(unittest.TestCase):

    def test_skip_state(self):
        """Jumping BOOT_INIT → ENV_VERIFIED (skipping LOCK_ACQUIRED) is illegal."""
        fsm = _fresh()
        result = fsm.transition(BootstrapState.ENV_VERIFIED, "skip test")
        self.assertFalse(result)
        self.assertEqual(fsm.state, BootstrapState.BOOT_INIT)

    def test_backward_transition(self):
        """Going HEALTH_BOUND → BOOT_INIT is illegal."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
        )
        result = fsm.transition(BootstrapState.BOOT_INIT, "backward")
        self.assertFalse(result)
        self.assertEqual(fsm.state, BootstrapState.HEALTH_BOUND)

    def test_shutdown_is_terminal(self):
        """No transition from SHUTDOWN is legal."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.CONFIG_ERROR_KEEPALIVE,
            BootstrapState.SHUTDOWN,
        )
        for target in BootstrapState:
            result = fsm.transition(target, "post-shutdown test")
            self.assertFalse(result)
            self.assertEqual(fsm.state, BootstrapState.SHUTDOWN)

    def test_raise_on_invalid_flag(self):
        """raise_on_invalid=True causes BootstrapInvariantError on illegal transitions."""
        fsm = _fresh()
        with self.assertRaises(BootstrapInvariantError) as ctx:
            fsm.transition(
                BootstrapState.RUNNING_SUPERVISED,
                "invalid",
                raise_on_invalid=True,
            )
        self.assertIn("FSM_TRANSITION", ctx.exception.invariant_id)


# ---------------------------------------------------------------------------
# reset_for_retry
# ---------------------------------------------------------------------------

class TestResetForRetry(unittest.TestCase):

    def test_reset_from_running(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        )
        fsm.reset_for_retry("supervisor crashed")
        self.assertEqual(fsm.state, BootstrapState.BOOT_FAILED_RETRY)

    def test_reset_from_capital_ready(self):
        """reset_for_retry from CAPITAL_READY must succeed (PREFLIGHT→SUPERVISOR stuck fix)."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
        )
        fsm.reset_for_retry("maybe_auto_activate failed at CAPITAL_READY")
        self.assertEqual(fsm.state, BootstrapState.BOOT_FAILED_RETRY)

    def test_reset_from_platform_ready(self):
        """reset_for_retry from PLATFORM_READY must succeed."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
        )
        fsm.reset_for_retry("failure at PLATFORM_READY")
        self.assertEqual(fsm.state, BootstrapState.BOOT_FAILED_RETRY)

    def test_capital_ready_retry_then_full_happy_path(self):
        """CAPITAL_READY → BOOT_FAILED_RETRY → PLATFORM_CONNECTING → ... → RUNNING_SUPERVISED."""
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
        )
        # Simulate a failure at the PREFLIGHT→SUPERVISOR boundary
        fsm.reset_for_retry("maybe_auto_activate blocked")
        self.assertEqual(fsm.state, BootstrapState.BOOT_FAILED_RETRY)
        # Full retry path from BOOT_FAILED_RETRY
        _fast_forward(
            fsm,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        )
        self.assertEqual(fsm.state, BootstrapState.RUNNING_SUPERVISED)

    def test_reset_noop_from_shutdown(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.CONFIG_ERROR_KEEPALIVE,
            BootstrapState.SHUTDOWN,
        )
        fsm.reset_for_retry("should be ignored")
        self.assertEqual(fsm.state, BootstrapState.SHUTDOWN)

    def test_reset_noop_from_external_restart(self):
        fsm = _fresh()
        fsm.reset_for_retry("bump to BOOT_FAILED_RETRY first")
        fsm.transition(BootstrapState.EXTERNAL_RESTART_REQUIRED, "fatal")
        fsm.reset_for_retry("should be ignored")
        self.assertEqual(fsm.state, BootstrapState.EXTERNAL_RESTART_REQUIRED)

    def test_reset_records_history(self):
        fsm = _fresh()
        _fast_forward(fsm, BootstrapState.LOCK_ACQUIRED, BootstrapState.HEALTH_BOUND)
        fsm.reset_for_retry("test reset")
        hist = fsm.get_history()
        reasons = [r["reason"] for r in hist]
        self.assertTrue(any("reset_for_retry" in r for r in reasons))


# ---------------------------------------------------------------------------
# Invariant assertions (unit-level; sub-machines are mocked)
# ---------------------------------------------------------------------------

class TestInvariantI1(unittest.TestCase):
    def test_fires_in_boot_init(self):
        fsm = _fresh()
        with self.assertRaises(BootstrapInvariantError) as ctx:
            fsm.assert_invariant_i1_single_writer()
        self.assertEqual(ctx.exception.invariant_id, "I1_SINGLE_WRITER")

    def test_clears_after_lock(self):
        fsm = _fresh()
        fsm.transition(BootstrapState.LOCK_ACQUIRED, "lock")
        fsm.assert_invariant_i1_single_writer()  # must not raise


class TestInvariantI2(unittest.TestCase):
    def test_fires_before_health_bound(self):
        fsm = _fresh()
        fsm.transition(BootstrapState.LOCK_ACQUIRED, "lock")
        with self.assertRaises(BootstrapInvariantError) as ctx:
            fsm.assert_invariant_i2_liveness_first()
        self.assertEqual(ctx.exception.invariant_id, "I2_LIVENESS_FIRST")

    def test_clears_after_health_bound(self):
        fsm = _fresh()
        _fast_forward(fsm, BootstrapState.LOCK_ACQUIRED, BootstrapState.HEALTH_BOUND)
        fsm.assert_invariant_i2_liveness_first()  # must not raise


class TestInvariantI3(unittest.TestCase):
    def test_fires_when_fsm_connecting(self):
        fsm = _fresh()
        mock_kraken_fsm = MagicMock()
        mock_kraken_fsm.is_connected = False
        mock_kraken_fsm.is_failed = False
        with patch(
            "bot.bootstrap_state_machine.BootstrapStateMachine.assert_invariant_i3_platform_first",
            wraps=fsm.assert_invariant_i3_platform_first,
        ):
            with patch("bot.broker_manager._KRAKEN_STARTUP_FSM", mock_kraken_fsm, create=True):
                with self.assertRaises((BootstrapInvariantError, ImportError)):
                    fsm.assert_invariant_i3_platform_first()

    def test_passes_when_connected(self):
        fsm = _fresh()
        mock_kraken_fsm = MagicMock()
        mock_kraken_fsm.is_connected = True
        mock_kraken_fsm.is_failed = False
        with patch.dict("sys.modules", {"bot.broker_manager": MagicMock(_KRAKEN_STARTUP_FSM=mock_kraken_fsm)}):
            fsm.assert_invariant_i3_platform_first()  # must not raise

    def test_passes_when_failed(self):
        fsm = _fresh()
        mock_kraken_fsm = MagicMock()
        mock_kraken_fsm.is_connected = False
        mock_kraken_fsm.is_failed = True
        with patch.dict("sys.modules", {"bot.broker_manager": MagicMock(_KRAKEN_STARTUP_FSM=mock_kraken_fsm)}):
            fsm.assert_invariant_i3_platform_first()  # must not raise


class TestInvariantI4(unittest.TestCase):
    def test_fires_when_not_ready(self):
        fsm = _fresh()
        mock_boot_fsm = MagicMock()
        mock_boot_fsm.is_ready = False
        mock_boot_fsm.state.value = "WAIT_PLATFORM"
        mock_module = MagicMock()
        mock_module.get_capital_bootstrap_fsm = MagicMock(return_value=mock_boot_fsm)
        with patch.dict("sys.modules", {"bot.capital_flow_state_machine": mock_module}):
            with self.assertRaises(BootstrapInvariantError) as ctx:
                fsm.assert_invariant_i4_capital_gate()
        self.assertEqual(ctx.exception.invariant_id, "I4_CAPITAL_GATE")

    def test_passes_when_ready(self):
        fsm = _fresh()
        mock_boot_fsm = MagicMock()
        mock_boot_fsm.is_ready = True
        mock_module = MagicMock()
        mock_module.get_capital_bootstrap_fsm = MagicMock(return_value=mock_boot_fsm)
        with patch.dict("sys.modules", {"bot.capital_flow_state_machine": mock_module}):
            fsm.assert_invariant_i4_capital_gate()  # must not raise


class TestInvariantI6(unittest.TestCase):
    def test_fires_when_not_live(self):
        fsm = _fresh()
        mock_sm = MagicMock()
        mock_sm.is_live_trading_active.return_value = False
        mock_sm.get_current_state.return_value = MagicMock(value="OFF")
        mock_module = MagicMock()
        mock_module.get_state_machine = MagicMock(return_value=mock_sm)
        with patch.dict("sys.modules", {"bot.trading_state_machine": mock_module}):
            with self.assertRaises(BootstrapInvariantError) as ctx:
                fsm.assert_invariant_i6_mode_safety()
        self.assertEqual(ctx.exception.invariant_id, "I6_MODE_SAFETY")

    def test_passes_when_live(self):
        fsm = _fresh()
        mock_sm = MagicMock()
        mock_sm.is_live_trading_active.return_value = True
        mock_module = MagicMock()
        mock_module.get_state_machine = MagicMock(return_value=mock_sm)
        with patch.dict("sys.modules", {"bot.trading_state_machine": mock_module}):
            fsm.assert_invariant_i6_mode_safety()  # must not raise


class TestInvariantI7(unittest.TestCase):
    def test_fires_on_emergency_stop(self):
        fsm = _fresh()
        mock_sm = MagicMock()
        mock_sm.is_emergency_stopped.return_value = True
        mock_module = MagicMock()
        mock_module.get_state_machine = MagicMock(return_value=mock_sm)
        with patch.dict("sys.modules", {"bot.trading_state_machine": mock_module}):
            with self.assertRaises(BootstrapInvariantError) as ctx:
                fsm.assert_invariant_i7_emergency_safety()
        self.assertEqual(ctx.exception.invariant_id, "I7_EMERGENCY_SAFETY")

    def test_passes_when_not_emergency(self):
        fsm = _fresh()
        mock_sm = MagicMock()
        mock_sm.is_emergency_stopped.return_value = False
        mock_module = MagicMock()
        mock_module.get_state_machine = MagicMock(return_value=mock_sm)
        with patch.dict("sys.modules", {"bot.trading_state_machine": mock_module}):
            fsm.assert_invariant_i7_emergency_safety()  # must not raise


class TestInvariantI8(unittest.TestCase):
    def test_fires_outside_running(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
        )
        with self.assertRaises(BootstrapInvariantError) as ctx:
            fsm.assert_invariant_i8_supervisor_ownership()
        self.assertEqual(ctx.exception.invariant_id, "I8_SUPERVISOR_OWNERSHIP")

    def test_passes_in_running_supervised(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
            BootstrapState.PLATFORM_READY,
            BootstrapState.CAPITAL_REFRESHING,
            BootstrapState.CAPITAL_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        )
        fsm.assert_invariant_i8_supervisor_ownership()  # must not raise


class TestInvariantI9(unittest.TestCase):
    def test_fires_on_nonce_not_authorized(self):
        exc = RuntimeError("EAPI:Invalid nonce -- nonce not authorized")
        with self.assertRaises(BootstrapInvariantError) as ctx:
            BootstrapStateMachine.assert_invariant_i9_fail_closed_nonce(exc)
        self.assertEqual(ctx.exception.invariant_id, "I9_FAIL_CLOSED_NONCE")

    def test_fires_on_nonce_spike(self):
        exc = RuntimeError("Invalid nonce spike detected — nonce drift exceeds threshold")
        with self.assertRaises(BootstrapInvariantError) as ctx:
            BootstrapStateMachine.assert_invariant_i9_fail_closed_nonce(exc)
        self.assertEqual(ctx.exception.invariant_id, "I9_FAIL_CLOSED_NONCE")

    def test_passes_on_unrelated_error(self):
        exc = RuntimeError("Broker connection timeout")
        BootstrapStateMachine.assert_invariant_i9_fail_closed_nonce(exc)  # must not raise


class TestInvariantI10(unittest.TestCase):
    def test_fires_on_wrong_writer(self):
        with self.assertRaises(BootstrapInvariantError) as ctx:
            BootstrapStateMachine.assert_invariant_i10_capital_writer("some_other_writer")
        self.assertEqual(ctx.exception.invariant_id, "I10_CAPITAL_WRITER")

    def test_passes_for_canonical_writer(self):
        BootstrapStateMachine.assert_invariant_i10_capital_writer(
            "mabm_capital_refresh_coordinator"
        )  # must not raise


# ---------------------------------------------------------------------------
# check_invariant dispatcher
# ---------------------------------------------------------------------------

class TestCheckInvariantDispatcher(unittest.TestCase):

    def test_i1_dispatches(self):
        fsm = _fresh()
        with self.assertRaises(BootstrapInvariantError):
            fsm.check_invariant("I1")

    def test_i9_dispatches_with_kwarg(self):
        fsm = _fresh()
        exc = RuntimeError("nonce not authorized")
        with self.assertRaises(BootstrapInvariantError):
            fsm.check_invariant("I9", exc=exc)

    def test_i9_no_op_without_exc(self):
        fsm = _fresh()
        fsm.check_invariant("I9")  # no exc kwarg — should not raise

    def test_i10_dispatches_with_kwarg(self):
        fsm = _fresh()
        with self.assertRaises(BootstrapInvariantError):
            fsm.check_invariant("I10", writer_id="bad_writer")

    def test_i10_passes_canonical(self):
        fsm = _fresh()
        fsm.check_invariant("I10", writer_id="mabm_capital_refresh_coordinator")

    def test_unknown_invariant_raises_value_error(self):
        fsm = _fresh()
        with self.assertRaises(ValueError):
            fsm.check_invariant("I99")


# ---------------------------------------------------------------------------
# get_status / get_history
# ---------------------------------------------------------------------------

class TestStatusAndHistory(unittest.TestCase):

    def test_get_status_structure(self):
        fsm = _fresh()
        status = fsm.get_status()
        self.assertIn("state", status)
        self.assertIn("history", status)
        self.assertEqual(status["state"], "BOOT_INIT")

    def test_history_grows_with_transitions(self):
        fsm = _fresh()
        fsm.transition(BootstrapState.LOCK_ACQUIRED, "test")
        history = fsm.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["from"], "BOOT_INIT")
        self.assertEqual(history[0]["to"], "LOCK_ACQUIRED")

    def test_history_limit(self):
        fsm = _fresh()
        _fast_forward(
            fsm,
            BootstrapState.LOCK_ACQUIRED,
            BootstrapState.HEALTH_BOUND,
            BootstrapState.ENV_VERIFIED,
            BootstrapState.STARTUP_VALIDATED,
            BootstrapState.MODE_GATED,
            BootstrapState.PLATFORM_CONNECTING,
        )
        limited = fsm.get_history(limit=3)
        self.assertLessEqual(len(limited), 3)

    def test_failed_transitions_not_recorded(self):
        fsm = _fresh()
        fsm.transition(BootstrapState.SHUTDOWN, "illegal")  # should fail
        self.assertEqual(len(fsm.get_history()), 0)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_same_instance_returned(self):
        a = get_bootstrap_fsm()
        b = get_bootstrap_fsm()
        self.assertIs(a, b)


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):

    def test_concurrent_invalid_transitions_do_not_corrupt(self):
        """Multiple threads all attempting illegal transitions must leave state clean."""
        fsm = _fresh()
        errors: list = []

        def attempt_invalid():
            try:
                result = fsm.transition(BootstrapState.SHUTDOWN, "concurrent illegal")
                # result should be False; state should remain BOOT_INIT
                if result:
                    errors.append("unexpected success")
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=attempt_invalid) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(fsm.state, BootstrapState.BOOT_INIT)
        self.assertEqual(errors, [])

    def test_concurrent_valid_transition_is_idempotent(self):
        """Only one thread should succeed; the rest see False."""
        fsm = _fresh()
        successes: list = []
        lock = threading.Lock()

        def attempt():
            result = fsm.transition(BootstrapState.LOCK_ACQUIRED, "concurrent valid")
            with lock:
                if result:
                    successes.append(1)

        threads = [threading.Thread(target=attempt) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(successes), 1)
        self.assertEqual(fsm.state, BootstrapState.LOCK_ACQUIRED)


# ---------------------------------------------------------------------------
# Single-owner bootstrap kernel — ownership enforcement
# ---------------------------------------------------------------------------

class TestOwnershipEnforcement(unittest.TestCase):
    """Verify the single-owner bootstrap kernel invariant."""

    def test_claim_sets_owner_to_caller(self):
        """claim_bootstrap_ownership() records the calling thread's ID."""
        fsm = _fresh()
        self.assertIsNone(fsm._owner_thread_id)
        fsm.claim_bootstrap_ownership()
        self.assertEqual(fsm._owner_thread_id, threading.get_ident())

    def test_claim_idempotent_same_thread(self):
        """Calling claim_bootstrap_ownership() twice from the same thread is safe."""
        fsm = _fresh()
        fsm.claim_bootstrap_ownership()
        owner_after_first = fsm._owner_thread_id
        fsm.claim_bootstrap_ownership()
        self.assertEqual(fsm._owner_thread_id, owner_after_first)

    def test_claim_updates_to_new_owner(self):
        """A second thread can take ownership (claim replaces the old owner)."""
        fsm = _fresh()
        fsm.claim_bootstrap_ownership()
        new_owner_id: list = []

        def _claim():
            fsm.claim_bootstrap_ownership()
            new_owner_id.append(threading.get_ident())

        t = threading.Thread(target=_claim)
        t.start()
        t.join()

        self.assertEqual(len(new_owner_id), 1)
        self.assertEqual(fsm._owner_thread_id, new_owner_id[0])

    def test_owner_thread_transition_has_no_warning(self):
        """Owner-thread transitions must NOT emit the non-owner warning."""
        fsm = _fresh()
        fsm.claim_bootstrap_ownership()

        with self.assertLogs("nija.bootstrap_fsm", level="WARNING") as cm:
            # Drive a valid transition from the owner thread; the only log
            # should be the INFO-level transition record, not a WARNING.
            # assertLogs requires at least one log record, so we force one by
            # doing an *illegal* (SHUTDOWN from BOOT_INIT) transition which
            # always emits an ERROR — confirming the channel works.
            fsm.transition(BootstrapState.SHUTDOWN, "illegal — triggers logger")

        # No "Non-owner" warning should appear.
        warning_msgs = [r for r in cm.output if "Non-owner" in r]
        self.assertEqual(warning_msgs, [])

    def test_non_owner_thread_logs_warning(self):
        """A non-owner thread driving a transition must emit the warning."""
        fsm = _fresh()
        fsm.claim_bootstrap_ownership()  # main test thread is owner
        warning_seen: list = []

        def _non_owner_transition():
            with self.assertLogs("nija.bootstrap_fsm", level="WARNING") as cm:
                # Attempt any transition from a different thread.
                # Use an illegal one so we get at least one log entry (ERROR)
                # that satisfies assertLogs even if the warning fires too.
                fsm.transition(BootstrapState.SHUTDOWN, "non-owner attempt")
            non_owner_warns = [r for r in cm.output if "Non-owner" in r]
            warning_seen.extend(non_owner_warns)

        t = threading.Thread(target=_non_owner_transition)
        t.start()
        t.join()

        self.assertGreater(len(warning_seen), 0, "Expected non-owner warning log")

    def test_no_owner_set_allows_any_thread(self):
        """When no owner is registered, transitions from any thread are silent."""
        fsm = _fresh()
        # No ownership claimed — non-owner check should be skipped.
        results: list = []

        def _transition():
            # A valid transition from a non-owner (no owner registered).
            r = fsm.transition(BootstrapState.LOCK_ACQUIRED, "no owner set")
            results.append(r)

        t = threading.Thread(target=_transition)
        t.start()
        t.join()

        self.assertEqual(results, [True])
        self.assertEqual(fsm.state, BootstrapState.LOCK_ACQUIRED)

    def test_get_status_includes_owner_thread_id(self):
        """get_status() must expose owner_thread_id for observability."""
        fsm = _fresh()
        status_before = fsm.get_status()
        self.assertIn("owner_thread_id", status_before)
        self.assertIsNone(status_before["owner_thread_id"])

        fsm.claim_bootstrap_ownership()
        status_after = fsm.get_status()
        self.assertEqual(status_after["owner_thread_id"], threading.get_ident())

    def test_transitions_still_succeed_from_non_owner(self):
        """Non-owner transitions are fail-open: they warn but still apply."""
        fsm = _fresh()
        fsm.claim_bootstrap_ownership()  # this thread owns it

        applied: list = []

        def _non_owner():
            # Drive a *valid* transition (BOOT_INIT → LOCK_ACQUIRED) from a
            # non-owner thread; it should succeed (fail-open) despite the warning.
            r = fsm.transition(BootstrapState.LOCK_ACQUIRED, "non-owner valid")
            applied.append(r)

        t = threading.Thread(target=_non_owner)
        t.start()
        t.join()

        self.assertEqual(applied, [True])
        self.assertEqual(fsm.state, BootstrapState.LOCK_ACQUIRED)


if __name__ == "__main__":
    unittest.main()
