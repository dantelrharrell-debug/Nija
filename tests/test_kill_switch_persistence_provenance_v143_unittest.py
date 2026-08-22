from __future__ import annotations

import importlib.util
import os
import threading
import types
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

    def test_installer_reasserts_wrappers_after_replay_drift(self) -> None:
        class FakeKillSwitch:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._activation_history = [
                    {"source": "AUTOMATIC", "reason": HEARTBEAT},
                    dict(FILE),
                    dict(FILE),
                ]

            def get_status(self):
                with self._lock:
                    return {"is_active": True, "recent_history": self._activation_history[-5:]}

        def base_causal(status):
            history = list(status.get("recent_history") or [])
            latest = history[-1] if history else {}
            return str(latest.get("reason") or ""), str(latest.get("source") or "")

        v140 = types.SimpleNamespace(_causal_activation=base_causal)
        v131 = types.SimpleNamespace(_causal_activation=base_causal)
        v130 = types.SimpleNamespace(_latest_activation=base_causal)
        manifest = types.SimpleNamespace(_REQUIRED_FLAGS={}, _INSTALLERS=tuple(), DECLARED_RELEASE_ID="old", RELEASE_ID="old")
        kill_module = types.SimpleNamespace(KillSwitch=FakeKillSwitch)
        modules = {
            "bot.kill_switch": kill_module,
            "bot.runtime_killswitch_authority_liveness_patch": v140,
            "bot.readiness_killswitch_causality_v131_patch": v131,
            "bot.kill_switch_stale_heartbeat_recovery_v130_patch": v130,
            "bot.runtime_release_manifest_patch": manifest,
        }

        original_import = mod.importlib.import_module
        original_installed = mod._INSTALLED
        original_flag = os.environ.get(mod._FLAG)
        original_reassert = os.environ.get(mod._REASSERT_FLAG)
        original_v140_ready = os.environ.get("NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY")
        original_v142_ready = os.environ.get("NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY")
        mod.importlib.import_module = lambda name: modules[name] if name in modules else original_import(name)
        os.environ["NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"] = "1"
        os.environ["NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY"] = "1"
        mod._INSTALLED = False
        try:
            self.assertTrue(mod.install_import_hook())
            first_status_owner = FakeKillSwitch.get_status
            self.assertTrue(getattr(first_status_owner, mod._PATCH_ATTR, False))
            first_v140 = v140._causal_activation
            first_v131 = v131._causal_activation
            self.assertTrue(getattr(first_v140, mod._PATCH_ATTR, False))
            self.assertTrue(getattr(first_v131, mod._PATCH_ATTR, False))

            # Simulate compatibility/import replay replacing all three anchors
            # while the process-local installed flag remains set.
            def drifted_status(self):
                with self._lock:
                    return {"is_active": True, "recent_history": self._activation_history[-5:]}

            FakeKillSwitch.get_status = drifted_status
            v140._causal_activation = base_causal
            v131._causal_activation = base_causal
            v130._latest_activation = base_causal

            self.assertTrue(mod.install_import_hook())
            self.assertTrue(getattr(FakeKillSwitch.get_status, mod._PATCH_ATTR, False))
            self.assertTrue(getattr(v140._causal_activation, mod._PATCH_ATTR, False))
            self.assertTrue(getattr(v131._causal_activation, mod._PATCH_ATTR, False))
            self.assertIs(v130._latest_activation, v131._causal_activation)
            self.assertEqual(os.environ.get(mod._REASSERT_FLAG), "1")

            status = FakeKillSwitch().get_status()
            self.assertEqual(status[mod._META_KEY].get("reason"), HEARTBEAT)
            reason, source = v140._causal_activation(status)
            self.assertEqual(reason, HEARTBEAT)
            self.assertEqual(source, "AUTOMATIC")
        finally:
            mod.importlib.import_module = original_import
            mod._INSTALLED = original_installed
            if original_flag is None:
                os.environ.pop(mod._FLAG, None)
            else:
                os.environ[mod._FLAG] = original_flag
            if original_reassert is None:
                os.environ.pop(mod._REASSERT_FLAG, None)
            else:
                os.environ[mod._REASSERT_FLAG] = original_reassert
            if original_v140_ready is None:
                os.environ.pop("NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY", None)
            else:
                os.environ["NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"] = original_v140_ready
            if original_v142_ready is None:
                os.environ.pop("NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY", None)
            else:
                os.environ["NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY"] = original_v142_ready


if __name__ == "__main__":
    unittest.main()
