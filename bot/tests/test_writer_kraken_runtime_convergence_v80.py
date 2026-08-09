from __future__ import annotations

import importlib
import unittest
from unittest import mock


class WriterKrakenConvergenceV80Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.writer_kraken_runtime_convergence_v80_patch")

    def test_missing_runtime_uses_v77_reacquisition(self) -> None:
        with mock.patch.object(self.mod.v77, "_runtime", return_value=(None, "entrypoint_runtime_unavailable")), \
             mock.patch.object(self.mod, "_heartbeat_stale", return_value=(True, "heartbeat_stale")), \
             mock.patch.object(self.mod.v77, "repair_or_reacquire", return_value=(True, 4001, "exact_owner_reconstituted")) as repair:
            state = self.mod.reconcile_writer_once()
        self.assertTrue(state["ok"])
        self.assertEqual(state["generation"], 4001)
        self.assertEqual(state["action"], "reconstituted_or_reacquired")
        repair.assert_called_once()

    def test_runtime_not_acquired_uses_canonical_reacquire(self) -> None:
        runtime = mock.Mock(acquired=False, lost=False)
        with mock.patch.object(self.mod.v77, "_runtime", return_value=(runtime, "")), \
             mock.patch.object(self.mod, "_heartbeat_stale", return_value=(True, "heartbeat_stale")), \
             mock.patch.object(self.mod.v77, "repair_or_reacquire", return_value=(True, 3424, "exact_owner_reconstituted")):
            state = self.mod.reconcile_writer_once()
        self.assertTrue(state["ok"])
        self.assertFalse(state["acquired"])
        self.assertTrue(state["heartbeat_stale"])

    def test_writer_failure_blocks_kraken_recovery(self) -> None:
        with mock.patch.object(self.mod, "reconcile_writer_once", return_value={"ok": False, "reason": "foreign_owner"}), \
             mock.patch.object(self.mod.v44, "reconcile_once") as kraken:
            state = self.mod.reconcile_kraken_once()
        self.assertFalse(state["ok"])
        self.assertIn("writer_not_ready", state["reason"])
        kraken.assert_not_called()

    def test_writer_success_allows_authenticated_kraken_recovery(self) -> None:
        with mock.patch.object(self.mod, "reconcile_writer_once", return_value={"ok": True, "reason": "healthy"}), \
             mock.patch.object(self.mod.v44, "reconcile_once", return_value={
                 "ok": True,
                 "connected": False,
                 "action": "recovery_started",
                 "reason": "disconnected_recovery_started",
             }) as kraken:
            state = self.mod.reconcile_kraken_once()
        self.assertTrue(state["ok"])
        self.assertEqual(state["action"], "recovery_started")
        kraken.assert_called_once()

    def test_healthy_writer_does_not_reacquire(self) -> None:
        runtime = mock.Mock(acquired=True, lost=False)
        with mock.patch.object(self.mod.v77, "_runtime", return_value=(runtime, "")), \
             mock.patch.object(self.mod, "_heartbeat_stale", return_value=(False, "heartbeat_healthy")), \
             mock.patch.object(self.mod.v77, "repair_or_reacquire") as repair:
            state = self.mod.reconcile_writer_once()
        self.assertTrue(state["ok"])
        self.assertEqual(state["reason"], "writer_runtime_and_heartbeat_healthy")
        repair.assert_not_called()


if __name__ == "__main__":
    unittest.main()
