"""
Tests for the broker_connected readiness gate in the bootstrap sequence.

Verifies that:
- When MABM is None, broker_connected is marked not-applicable (True in table).
- When MABM has fully ready brokers, broker_connected is marked ready (True).
- When MABM has no ready brokers, broker_connected remains False so policy
  evaluation can decide whether startup should block or degrade.
- After all flags are set the readiness table reports is_ready() == True.
"""

from __future__ import annotations

import threading
import time
import unittest

from bot import readiness_table


class TestReadinessBrokerGate(unittest.TestCase):
    """Unit tests for the broker_connected readiness flag path."""

    def setUp(self):
        readiness_table.reset()

    def tearDown(self):
        readiness_table.reset()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mark_all_except_broker(self):
        """Mark every canonical key except broker_connected as ready."""
        for key in readiness_table.KEYS:
            if key != "broker_connected":
                readiness_table.mark_ready(key)

    # ------------------------------------------------------------------
    # Core readiness-table contract
    # ------------------------------------------------------------------

    def test_mark_ready_sets_key_true(self):
        readiness_table.mark_ready("broker_connected")
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_mark_not_applicable_also_sets_key_true(self):
        readiness_table.mark_not_applicable("broker_connected", reason="test")
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_set_ready_prevents_true_to_false_regression(self):
        readiness_table.mark_ready("broker_connected")
        readiness_table.set_ready("broker_connected", False)
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_is_ready_requires_all_keys(self):
        self._mark_all_except_broker()
        self.assertFalse(readiness_table.is_ready())
        readiness_table.mark_ready("broker_connected")
        self.assertTrue(readiness_table.is_ready())

    def test_is_ready_true_when_not_applicable_used(self):
        """mark_not_applicable satisfies the gate the same way mark_ready does."""
        self._mark_all_except_broker()
        readiness_table.mark_not_applicable("broker_connected", reason="no mabm")
        self.assertTrue(readiness_table.is_ready())

    def test_pending_returns_unset_keys(self):
        self._mark_all_except_broker()
        pending = readiness_table.pending()
        self.assertEqual(pending, ["broker_connected"])

    def test_snapshot_is_copy(self):
        snap1 = readiness_table.snapshot()
        readiness_table.mark_ready("broker_connected")
        snap2 = readiness_table.snapshot()
        self.assertFalse(snap1["broker_connected"])
        self.assertTrue(snap2["broker_connected"])

    def test_version_advances_when_value_changes(self):
        version1, _ = readiness_table.snapshot_with_version()
        readiness_table.mark_ready("broker_connected")
        version2, snapshot = readiness_table.snapshot_with_version()
        self.assertGreater(version2, version1)
        self.assertTrue(snapshot["broker_connected"])

    # ------------------------------------------------------------------
    # Simulate the bootstrap broker_connected gate logic
    # ------------------------------------------------------------------

    def _simulate_broker_gate(self, broker_manager, *, timeout_s: float = 2.0):
        """
        Mirrors the broker_connected gate logic introduced in bot.py.

        Parameters
        ----------
        broker_manager : object or None
            Fake MABM with all_brokers_fully_ready().
        timeout_s : float
            Maximum seconds to wait for readiness (shortened for tests).
        """
        if broker_manager is None:
            readiness_table.mark_not_applicable(
                "broker_connected",
                reason="MABM unavailable in this deployment",
            )
        elif hasattr(broker_manager, "all_brokers_fully_ready"):
            deadline = time.monotonic() + timeout_s
            while (
                not bool(broker_manager.all_brokers_fully_ready())
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if bool(broker_manager.all_brokers_fully_ready()):
                readiness_table.mark_ready("broker_connected")
            # Timeout path intentionally leaves broker_connected=False.
        else:
            # Unknown manager contract intentionally leaves broker_connected=False.
            return

    def test_gate_none_mabm_marks_not_applicable(self):
        self._simulate_broker_gate(None)
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_gate_ready_broker_marks_ready(self):
        class _ReadyMABM:
            def all_brokers_fully_ready(self):
                return True

        self._simulate_broker_gate(_ReadyMABM())
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_gate_not_ready_broker_remains_false(self):
        """When no broker becomes ready within timeout, broker_connected remains False."""
        class _NeverReadyMABM:
            def all_brokers_fully_ready(self):
                return False

        self._simulate_broker_gate(_NeverReadyMABM(), timeout_s=0.1)
        self.assertFalse(readiness_table.snapshot()["broker_connected"])

    def test_gate_broker_becomes_ready_within_timeout(self):
        """Broker that transitions to ready mid-wait is detected correctly."""
        ready = threading.Event()

        class _DelayedReadyMABM:
            def all_brokers_fully_ready(self):
                return ready.is_set()

        def _flip():
            time.sleep(0.05)
            ready.set()

        t = threading.Thread(target=_flip, daemon=True)
        t.start()

        self._simulate_broker_gate(_DelayedReadyMABM(), timeout_s=2.0)
        t.join(timeout=1.0)
        self.assertTrue(readiness_table.snapshot()["broker_connected"])

    def test_gate_mabm_without_method_remains_false(self):
        """MABM without readiness method leaves broker_connected unset."""
        class _LegacyMABM:
            pass  # no all_brokers_fully_ready attribute

        self._simulate_broker_gate(_LegacyMABM())
        self.assertFalse(readiness_table.snapshot()["broker_connected"])

    def test_full_readiness_table_passes_after_gate(self):
        """All eight canonical keys must be True for is_ready() to return True."""
        self._mark_all_except_broker()
        self._simulate_broker_gate(None)   # not_applicable path
        self.assertTrue(readiness_table.is_ready())
        self.assertEqual(readiness_table.pending(), [])


if __name__ == "__main__":
    unittest.main()
