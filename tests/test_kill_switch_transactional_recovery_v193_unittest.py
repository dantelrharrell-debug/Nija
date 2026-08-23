from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "kill_switch_transactional_recovery_v193_patch.py"
SPEC = importlib.util.spec_from_file_location("v193_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

HEARTBEAT = (
    "AUTHORITY_HEARTBEAT_EXPIRED: core_thread_dead - "
    "NIJA_CORE_THREAD_ALIVE is not set"
)
FILE = {"source": "FILE_SYSTEM", "reason": "Kill switch file detected"}
VERIFIED = {
    "reason": "verified recovery from retired authority-heartbeat/core-death restart persistence"
}


class KillSwitchTransactionalRecoveryV193Tests(unittest.TestCase):
    def test_crosses_only_verified_recovery_boundary(self) -> None:
        history = [
            {"source": "AUTOMATIC", "reason": HEARTBEAT},
            dict(VERIFIED),
            dict(FILE),
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause_v193(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertTrue(meta.get("verified_recovery_boundary_crossed"))
        self.assertEqual(meta.get("source"), "AUTOMATIC")
        self.assertEqual(meta.get("reason"), HEARTBEAT)

    def test_manual_deactivation_boundary_remains_blocked(self) -> None:
        history = [
            {"source": "AUTOMATIC", "reason": HEARTBEAT},
            {"reason": "operator manually cleared emergency stop after investigation"},
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause_v193(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("blocked"), "deactivation_boundary")

    def test_verified_boundary_does_not_cross_to_risk_stop(self) -> None:
        history = [
            {"source": "AUTO", "reason": "daily loss limit reached"},
            dict(VERIFIED),
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause_v193(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("blocked"), "verified_recovery_origin_not_retired_heartbeat")

    def test_verified_boundary_does_not_cross_forbidden_source(self) -> None:
        history = [
            {"source": "UI", "reason": HEARTBEAT},
            dict(VERIFIED),
            dict(FILE),
        ]
        meta = mod._derive_persisted_cause_v193(history)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("blocked"), "verified_recovery_origin_source_forbidden")

    def test_direct_current_stop_has_no_restart_metadata(self) -> None:
        history = [{"source": "AUTOMATIC", "reason": HEARTBEAT}]
        self.assertIsNone(mod._derive_persisted_cause_v193(history))

    def test_known_verified_boundary_strings_are_exact(self) -> None:
        self.assertTrue(
            mod._verified_recovery_boundary(
                "v130 verified recovery from retired pre-v129 authority-heartbeat startup race"
            )
        )
        self.assertTrue(
            mod._verified_recovery_boundary(
                "verified recovery from retired authority-heartbeat/core-death restart persistence"
            )
        )
        self.assertFalse(mod._verified_recovery_boundary("manual deactivation"))


if __name__ == "__main__":
    unittest.main()
