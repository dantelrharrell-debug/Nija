from __future__ import annotations

import importlib.util
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "kill_switch_persistence_provenance_v143_patch.py"
SPEC = importlib.util.spec_from_file_location("v143_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

HEARTBEAT = (
    "AUTHORITY_HEARTBEAT_EXPIRED: core_thread_dead - "
    "NIJA_CORE_THREAD_ALIVE is not set"
)
FILE = {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"}


class KillSwitchPersistenceProvenanceV143Tests(unittest.TestCase):
    def test_reconstructs_origin_beyond_recent_five_window(self) -> None:
        history = [{"source": "MANUAL", "reason": HEARTBEAT}] + [dict(FILE) for _ in range(7)]
        meta = mod._derive_persisted_cause(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("source"), "MANUAL")
        self.assertEqual(meta.get("reason"), HEARTBEAT)
        self.assertEqual(meta.get("persistence_records_skipped"), 6)

        # Canonical public status would expose only five FILE_SYSTEM records.
        status = {
            "is_active": True,
            "recent_history": history[-5:],
            mod._META_KEY: meta,
        }
        reason, source = mod._causal_activation_from_status(status)
        self.assertEqual(reason, HEARTBEAT)
        self.assertEqual(source, "MANUAL")

    def test_deactivation_is_hard_provenance_boundary(self) -> None:
        history = [
            {"source": "AUTOMATIC", "reason": HEARTBEAT},
            {"reason": "verified recovery from retired authority-heartbeat/core-death restart persistence"},
            dict(FILE),
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("blocked"), "deactivation_boundary")

        status = {
            "is_active": True,
            "recent_history": history,
            mod._META_KEY: meta,
        }
        reason, source = mod._causal_activation_from_status(status)
        self.assertEqual(reason, "v143_provenance_blocked:deactivation_boundary")
        self.assertEqual(source, "PROVENANCE_BOUNDARY")

    def test_new_manual_stop_after_deactivation_wins(self) -> None:
        history = [
            {"source": "AUTOMATIC", "reason": HEARTBEAT},
            {"reason": "operator verified prior recovery"},
            {"source": "MANUAL", "reason": "operator manual stop for maintenance"},
            dict(FILE),
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("source"), "MANUAL")
        self.assertEqual(meta.get("reason"), "operator manual stop for maintenance")

    def test_direct_new_stop_has_no_persistence_metadata(self) -> None:
        history = [{"source": "AUTOMATIC", "reason": HEARTBEAT}]
        self.assertIsNone(mod._derive_persisted_cause(history))

    def test_get_status_wrapper_keeps_recent_window_but_adds_compact_cause(self) -> None:
        class FakeKillSwitch:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._activation_history = [
                    {"source": "MANUAL", "reason": HEARTBEAT},
                    *[dict(FILE) for _ in range(8)],
                ]

            def get_status(self):
                with self._lock:
                    return {
                        "is_active": True,
                        "recent_history": self._activation_history[-5:],
                    }

        original_import = mod.importlib.import_module
        mod.importlib.import_module = lambda name: type("M", (), {"KillSwitch": FakeKillSwitch}) if name == "bot.kill_switch" else original_import(name)
        try:
            self.assertTrue(mod._patch_kill_switch_status())
            status = FakeKillSwitch().get_status()
        finally:
            mod.importlib.import_module = original_import

        self.assertEqual(len(status["recent_history"]), 5)
        self.assertEqual(status[mod._DEPTH_KEY], 9)
        self.assertEqual(status[mod._META_KEY].get("source"), "MANUAL")
        self.assertNotIn("full_history", status)


if __name__ == "__main__":
    unittest.main()
