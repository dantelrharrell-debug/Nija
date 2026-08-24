from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class KillSwitchFileProvenanceV213Tests(unittest.TestCase):
    def setUp(self) -> None:
        from bot.kill_switch_file_provenance_v213_patch import install

        self.assertTrue(install())

    def _new_switch_with_marker(self, reason: str):
        from bot.kill_switch import KillSwitch

        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        marker = root / KillSwitch.KILL_SWITCH_FILE
        marker.write_text(
            "ALL TRADING OPERATIONS HAVE BEEN HALTED\n\n"
            f"Reason: {reason}\n"
            "Activated: 2026-08-24T03:55:00+00:00\n",
            encoding="utf-8",
        )
        before = marker.read_bytes()
        ks = KillSwitch(base_path=str(root))
        return temp, root, marker, before, ks

    def test_restart_persistence_does_not_rewrite_existing_marker(self) -> None:
        temp, root, marker, before, ks = self._new_switch_with_marker(
            "AUTHORITY_HEARTBEAT_EXPIRED core_thread_dead"
        )
        self.addCleanup(temp.cleanup)

        self.assertTrue(ks.is_active())
        self.assertEqual(marker.read_bytes(), before)

        status = ks.get_status()
        latest = status["recent_history"][-1]
        self.assertEqual(latest["source"], "FILE_SYSTEM")
        self.assertIn("Kill switch file detected", latest["reason"])
        self.assertEqual(
            latest.get("persisted_marker_reason"),
            "AUTHORITY_HEARTBEAT_EXPIRED core_thread_dead",
        )
        self.assertFalse(latest.get("marker_rewritten", True))

        state = json.loads((root / KillSwitch.KILL_SWITCH_STATE_FILE).read_text())
        self.assertTrue(state["is_active"])
        self.assertEqual(state["history"][-1]["source"], "FILE_SYSTEM")

    def test_existing_marker_is_not_overwritten_by_later_activation_helper(self) -> None:
        temp, _root, marker, before, ks = self._new_switch_with_marker(
            "operator-created emergency stop"
        )
        self.addCleanup(temp.cleanup)

        # Exercise the patched creation helper directly: an already-existing
        # authoritative marker must never be truncated/replaced.
        ks._create_kill_file("different later reason")
        self.assertEqual(marker.read_bytes(), before)

    def test_missing_marker_still_uses_original_creation_path(self) -> None:
        from bot.kill_switch import KillSwitch

        with tempfile.TemporaryDirectory() as temp:
            ks = KillSwitch(base_path=temp)
            self.assertFalse(ks.is_active())
            ks.activate("manual safety test", source="MANUAL")
            marker = Path(temp) / KillSwitch.KILL_SWITCH_FILE
            self.assertTrue(marker.exists())
            text = marker.read_text(encoding="utf-8")
            self.assertIn("Reason: manual safety test", text)
            self.assertTrue(ks.is_active())


if __name__ == "__main__":
    unittest.main()
