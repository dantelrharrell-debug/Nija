from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class FilesystemEmergencyStopGuardedV214Tests(unittest.TestCase):
    def test_no_marker_means_no_recovery_attempt(self) -> None:
        from bot import filesystem_emergency_stop_replay_recovery_patch as v214

        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(v214, "_delegate_guarded_recovery") as delegated:
                self.assertFalse(v214.recover(temp))
                delegated.assert_not_called()

    def test_existing_marker_delegates_without_direct_removal(self) -> None:
        from bot import filesystem_emergency_stop_replay_recovery_patch as v214

        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "EMERGENCY_STOP"
            marker.write_text("Reason: operator stop\n", encoding="utf-8")
            before = marker.read_bytes()
            with mock.patch.object(v214, "_delegate_guarded_recovery", return_value=False) as delegated:
                self.assertFalse(v214.recover(temp))
                delegated.assert_called_once_with()
            self.assertTrue(marker.exists())
            self.assertEqual(marker.read_bytes(), before)

    def test_install_disables_legacy_text_heuristic(self) -> None:
        from bot import filesystem_emergency_stop_replay_recovery_patch as v214

        self.assertTrue(v214.install_import_hook())
        self.assertEqual(
            __import__("os").environ.get("NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_RECOVERY_ENABLED"),
            "false",
        )
        self.assertEqual(
            __import__("os").environ.get("NIJA_FILESYSTEM_EMERGENCY_STOP_REPLAY_GUARDED_V214_READY"),
            "1",
        )


if __name__ == "__main__":
    unittest.main()
