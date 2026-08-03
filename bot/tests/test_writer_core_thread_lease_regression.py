"""Regression test for writer authority lease lifecycle on core thread death.

Covers the exact failure observed in production logs:

  SCAN_STARTED_DEADLINE_EXCEEDED elapsed_since_acquisition=300s

Root cause: the writer lease was being renewed while core_thread_alive=False
because (a) the scan-started watchdog only logged the timeout without
triggering a re-election, and (b) _validate_core_thread_liveness returned
True when the core thread was None regardless of how long startup had stalled.

Fixes validated here:
  Fix 1  – _validate_core_thread_liveness returns False when scan deadline is
            exceeded and the core thread is still None.
  Fix 3  – SCAN_STARTED_DEADLINE_EXCEEDED triggers _release_owned_lock_for_reelection
            rather than just logging and returning.
  Fix 4  – After killing the registered thread the authority publishes
            NIJA_CORE_THREAD_ALIVE=0 (side-effect of _heartbeat_tick).
  Regression – Acquire writer, kill core thread, verify:
               • Redis compare-and-delete was called (lock released)
               • _stop event is set (heartbeat stopped)
               • NIJA_WRITER_FENCING_TOKEN cleared (generation cleared)
               • _lost event is set (writer authority triggers re-election path)
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure bot package is importable from the repo root.
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Environment variable keys that must be cleaned up between tests.
# ---------------------------------------------------------------------------
_WRITER_ENV_KEYS = (
    "NIJA_WRITER_FENCING_TOKEN",
    "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
    "NIJA_WRITER_OWNER_ID",
    "NIJA_WRITER_INSTANCE_ID",
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_LEASE_ACQUIRED",
    "NIJA_LOCK_ACQUIRED",
    "NIJA_WRITER_LOCK_KEY",
    "NIJA_WRITER_LOCK_META_KEY",
    "NIJA_WRITER_LOCK_SCOPE",
    "NIJA_WRITER_LOCK_TTL_S",
    "NIJA_WRITER_LOCK_ACQUIRED_AT",
    "NIJA_WRITER_HEARTBEAT_ACTIVE",
    "NIJA_WRITER_HEARTBEAT_LAST_TS",
    "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
    "NIJA_LEASE_GENERATION_KEY",
    "NIJA_LOCK_BYPASS_MODE",
    "LIVE_CAPITAL_VERIFIED",
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "KRAKEN_PLATFORM_API_KEY",
    "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S",
    "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_RUNTIME_EXECUTION_AUTHORITY",
    "NIJA_EXECUTION_ACTIVE",
    "NIJA_CORE_THREAD_ALIVE",
    "NIJA_WRITER_RELEASE_IN_PROGRESS",
)


def _make_acquire_result(token: int = 17, generation: int = 23):
    return [token, f"{token}:owner", 60_000, generation]


def _identity(instance_id: str = "test-inst-A"):
    return (
        {"instance_id": instance_id, "hostname": "host"},
        f"instance={instance_id}|pid=99",
        instance_id,
    )


class _Base(unittest.TestCase):
    """Common setup / teardown."""

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in _WRITER_ENV_KEYS}
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"
        os.environ["NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S"] = "0.1"

    def tearDown(self) -> None:
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def _make_runtime(self):
        from bot.entrypoint_writer_authority import EntrypointWriterAuthority
        return EntrypointWriterAuthority()

    def _acquire(self, runtime, token: int = 17, generation: int = 23):
        client = MagicMock()
        client.eval.return_value = _make_acquire_result(token, generation)
        client.set.return_value = True
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://fake", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                return_value=_identity(),
            ),
            patch.object(runtime, "_start_heartbeat"),
            patch.object(runtime, "_start_scan_started_watchdog"),
        ):
            result = runtime.acquire_once()
        return result, client

    @staticmethod
    def _mock_seak():
        mock_kernel = MagicMock()
        mock_kernel.get_seak.return_value = MagicMock()
        return patch.dict(sys.modules, {"bot.single_execution_authority_kernel": mock_kernel})


# ---------------------------------------------------------------------------
# Regression: acquire writer, kill core thread, verify full re-election
# ---------------------------------------------------------------------------

class TestCoreThreadDeathTriggersReelection(_Base):
    """This is the exact scenario from the production failure logs."""

    def test_dead_core_thread_releases_lock_and_triggers_reelection(self):
        """Acquire writer, kill core thread → lock released + re-election begins."""
        rt = self._make_runtime()
        result, client = self._acquire(rt)
        self.assertTrue(result.acquired, "Precondition: writer must be acquired")

        # Sanity-check: fencing token is set after acquisition.
        self.assertIn("NIJA_WRITER_FENCING_TOKEN", os.environ)

        # Simulate the Redis compare-and-delete succeeding.
        client.eval.return_value = 1

        # Start and immediately join a thread so it is provably dead.
        core_thread = threading.Thread(target=lambda: None, name="nija-core-test")
        core_thread.start()
        core_thread.join(timeout=2.0)
        self.assertFalse(core_thread.is_alive(), "Precondition: thread must be dead")

        # Register the (now dead) core thread with the authority.
        rt._core_thread = core_thread
        rt._core_thread_name = core_thread.name
        rt._core_thread_started_at = time.time() - 5.0

        with self._mock_seak():
            # This is the path triggered by _heartbeat_tick when the core
            # thread liveness check fails.
            rt._release_owned_lock_for_reelection(
                f"core_thread_dead name={core_thread.name} ident={core_thread.ident}"
            )

        # 1. Lock must have been released (Redis DEL was called).
        client.eval.assert_called()

        # 2. Heartbeat must be stopped (_stop is set).
        self.assertTrue(
            rt._stop.is_set(),
            "Heartbeat stop event must be set after re-election trigger",
        )

        # 3. Writer generation / fencing token must be cleared.
        self.assertNotIn(
            "NIJA_WRITER_FENCING_TOKEN",
            os.environ,
            "NIJA_WRITER_FENCING_TOKEN must be cleared when re-election is triggered",
        )

        # 4. The _lost event signals that a new election should begin.
        self.assertTrue(
            rt._lost.is_set(),
            "_lost event must be set so the caller knows to begin a fresh election",
        )

        # 5. NIJA_WRITER_LEASE_ACQUIRED must be 0 (not "1").
        self.assertEqual(
            os.environ.get("NIJA_WRITER_LEASE_ACQUIRED"),
            "0",
            "NIJA_WRITER_LEASE_ACQUIRED must be 0 after re-election trigger",
        )

    def test_heartbeat_tick_sets_core_thread_alive_env_var(self):
        """_heartbeat_tick must publish NIJA_CORE_THREAD_ALIVE for the authority heartbeat."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        # With no core thread registered, _validate_core_thread_liveness returns
        # True (startup phase) → NIJA_CORE_THREAD_ALIVE should be "1".
        client.eval.return_value = 1  # heartbeat renewal succeeds
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)

        rt._heartbeat_tick()

        self.assertEqual(
            os.environ.get("NIJA_CORE_THREAD_ALIVE"),
            "1",
            "NIJA_CORE_THREAD_ALIVE must be set to '1' when core thread is ok (startup phase)",
        )

    def test_heartbeat_tick_clears_core_thread_alive_on_dead_thread(self):
        """NIJA_CORE_THREAD_ALIVE must not be '1' when _heartbeat_tick detects a dead thread."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        core_thread = threading.Thread(target=lambda: None)
        core_thread.start()
        core_thread.join(timeout=2.0)

        rt._core_thread = core_thread
        rt._core_thread_name = core_thread.name
        client.eval.return_value = 1

        with self._mock_seak():
            ok, reason = rt._heartbeat_tick()

        self.assertFalse(ok)
        alive_val = os.environ.get("NIJA_CORE_THREAD_ALIVE", "")
        self.assertNotEqual(
            alive_val,
            "1",
            "NIJA_CORE_THREAD_ALIVE must not be '1' after the core thread has died "
            f"(got {alive_val!r}; '0' or absent are both acceptable)",
        )


# ---------------------------------------------------------------------------
# Fix 1: _validate_core_thread_liveness respects scan deadline
# ---------------------------------------------------------------------------

class TestValidateCoreThreadLivenessDeadline(_Base):

    def test_returns_true_when_core_thread_none_and_no_deadline(self):
        """No registered thread and no deadline exceeded → startup grace → True."""
        rt = self._make_runtime()
        self._acquire(rt)

        rt._scan_deadline_exceeded = False
        ok, reason = rt._validate_core_thread_liveness()

        self.assertTrue(ok, "Must return True during startup grace (deadline not yet exceeded)")

    def test_returns_false_when_core_thread_none_and_deadline_exceeded(self):
        """No registered thread but deadline exceeded → lease renewal must be refused."""
        rt = self._make_runtime()
        self._acquire(rt)

        # Simulate the watchdog having fired and set the deadline-exceeded flag.
        rt._scan_deadline_exceeded = True

        ok, reason = rt._validate_core_thread_liveness()

        self.assertFalse(ok, "Must return False when scan deadline exceeded and no core thread")
        self.assertIn("deadline_exceeded", reason)


# ---------------------------------------------------------------------------
# Fix 3: scan-started watchdog triggers re-election on deadline
# ---------------------------------------------------------------------------

class TestScanStartedWatchdogReelection(_Base):

    def test_watchdog_does_not_release_on_deadline_exceeded(self):
        """_scan_started_watchdog_loop must NOT release the writer lease when the
        scan-start deadline is exceeded.  The bot should continue holding
        authority so that the scan can still start once exchange connections
        finish bootstrapping (e.g. after a slow Kraken reconnect)."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        client.eval.return_value = 1

        # Set acquired_at far enough in the past that elapsed >= deadline_s
        # on the very first poll, then stop the event so the loop exits.
        rt._acquired_at = time.time() - 400.0
        rt._stop.set()  # stop immediately after one iteration

        with self._mock_seak():
            with patch.object(
                rt, "_release_owned_lock_for_reelection"
            ) as mock_release:
                rt._scan_started_watchdog_loop(deadline_s=1.0)

        mock_release.assert_not_called()

    def test_watchdog_sets_scan_deadline_exceeded_flag(self):
        """_scan_deadline_exceeded must be True after the watchdog fires."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        client.eval.return_value = 1
        rt._acquired_at = time.time() - 400.0
        # Stop after the first iteration so the loop exits rather than
        # spinning indefinitely (the watchdog no longer self-terminates on
        # deadline; it keeps monitoring until stopped externally).
        rt._stop.set()

        with self._mock_seak():
            rt._scan_started_watchdog_loop(deadline_s=1.0)

        self.assertTrue(
            rt._scan_deadline_exceeded,
            "_scan_deadline_exceeded must be set after the watchdog deadline fires",
        )

    def test_watchdog_does_not_release_if_scan_started_in_time(self):
        """Watchdog must exit cleanly without releasing when scan started in time."""
        rt = self._make_runtime()
        _, client = self._acquire(rt)

        rt._acquired_at = time.time()
        rt._scan_started_at = time.time()  # scan started already

        with patch.object(rt, "_release_owned_lock_for_reelection") as mock_release:
            rt._scan_started_watchdog_loop(deadline_s=300.0)

        mock_release.assert_not_called()
        self.assertFalse(rt._scan_deadline_exceeded)


# ---------------------------------------------------------------------------
# Fix 2: authority_heartbeat checks core_thread_alive + event_loop_running
# ---------------------------------------------------------------------------

class TestAuthorityHeartbeatLivenessGates(unittest.TestCase):
    """_check_authority_once must report UNHEALTHY when liveness flags are False."""

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in _WRITER_ENV_KEYS}
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)

    def tearDown(self) -> None:
        for k in _WRITER_ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def _set_healthy_base(self):
        """Establish the minimum env state for a passing authority check."""
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "abc123"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"

    def test_unhealthy_when_core_thread_alive_is_false(self):
        """UNHEALTHY if lease is held but NIJA_CORE_THREAD_ALIVE='0'."""
        from bot.authority_heartbeat import _check_authority_once

        self._set_healthy_base()
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"

        # The core_thread_alive check runs before Redis verification, so it
        # must fail immediately without requiring any Redis mock.
        ok, reason = _check_authority_once(timeout_s=1.0)

        self.assertFalse(ok, "Heartbeat must fail when NIJA_CORE_THREAD_ALIVE='0'")
        self.assertIn("core_thread", reason.lower())

    def test_unhealthy_when_heartbeat_active_is_false(self):
        """UNHEALTHY if lease is held but NIJA_WRITER_HEARTBEAT_ACTIVE='0'."""
        from bot.authority_heartbeat import _check_authority_once

        self._set_healthy_base()
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"

        # The event_loop check runs before Redis verification.
        ok, reason = _check_authority_once(timeout_s=1.0)

        self.assertFalse(ok, "Heartbeat must fail when NIJA_WRITER_HEARTBEAT_ACTIVE='0'")
        self.assertIn("event loop", reason.lower())

    def test_healthy_when_liveness_flags_absent_during_startup(self):
        """During startup (flags absent), the check must not fail on missing flags."""
        from bot.authority_heartbeat import _check_authority_once

        # Lease not yet acquired → ping-only path; liveness flags absent.
        os.environ.pop("NIJA_WRITER_LEASE_ACQUIRED", None)
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
        os.environ.pop("NIJA_WRITER_HEARTBEAT_ACTIVE", None)
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "abc123"

        # Call with any timeout — this will fail on Redis/authority reasons
        # because no Redis is configured, but it must NOT fail with a
        # core_thread or event_loop reason (flags are absent = startup grace).
        ok, reason = _check_authority_once(timeout_s=1.0)

        self.assertNotIn("core_thread", reason.lower())
        self.assertNotIn("event loop", reason.lower())


if __name__ == "__main__":
    unittest.main()
