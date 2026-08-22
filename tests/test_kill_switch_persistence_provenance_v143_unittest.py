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

    def test_causal_class_preserves_safety_categories(self) -> None:
        self.assertEqual(mod._causal_class(HEARTBEAT, "AUTOMATIC"), "retired_heartbeat_core_signature")
        self.assertEqual(mod._causal_class("operator manual stop", "MANUAL"), "manual_or_operator")
        self.assertEqual(mod._causal_class("drawdown loss limit reached", "AUTO"), "risk_or_drawdown")
        self.assertEqual(
            mod._causal_class("v143_provenance_blocked:origin_unavailable", "PROVENANCE_BOUNDARY"),
            "provenance_boundary",
        )

    def test_post_reassert_recheck_delegates_without_direct_clear(self) -> None:
        class FakeKillSwitch:
            def __init__(self) -> None:
                self.active = True
                self.deactivate_calls = 0

            def get_status(self):
                return {
                    "is_active": self.active,
                    "recent_history": [dict(FILE)],
                    mod._META_KEY: {"source": "AUTOMATIC", "reason": HEARTBEAT},
                }

            def deactivate(self, *args, **kwargs):
                self.deactivate_calls += 1
                raise AssertionError("v186 must never call deactivate directly")

        kill_switch = FakeKillSwitch()
        attempts = []

        def attempt():
            attempts.append(True)
            return False

        v140 = types.SimpleNamespace(
            _causal_activation=lambda status: mod._causal_activation_from_status(status)
        )
        v132 = types.SimpleNamespace(_attempt_persisted_stop_recovery=attempt)
        modules = {
            "bot.kill_switch": types.SimpleNamespace(get_kill_switch=lambda: kill_switch),
            "bot.runtime_killswitch_authority_liveness_patch": v140,
            "bot.readiness_killswitch_durability_v132_patch": v132,
        }
        original_import = mod.importlib.import_module
        mod.importlib.import_module = lambda name: modules[name] if name in modules else original_import(name)
        try:
            self.assertFalse(mod._post_reassert_recheck())
        finally:
            mod.importlib.import_module = original_import

        self.assertEqual(len(attempts), 1)
        self.assertEqual(kill_switch.deactivate_calls, 0)
        self.assertTrue(kill_switch.active)

    def test_post_reassert_recheck_manual_stop_remains_delegated_and_active(self) -> None:
        class FakeKillSwitch:
            def get_status(self):
                return {
                    "is_active": True,
                    "recent_history": [dict(FILE)],
                    mod._META_KEY: {
                        "source": "MANUAL",
                        "reason": "operator manual stop for maintenance",
                    },
                }

        calls = []
        v140 = types.SimpleNamespace(
            _causal_activation=lambda status: mod._causal_activation_from_status(status)
        )
        v132 = types.SimpleNamespace(
            _attempt_persisted_stop_recovery=lambda: calls.append("attempt") or False
        )
        modules = {
            "bot.kill_switch": types.SimpleNamespace(get_kill_switch=lambda: FakeKillSwitch()),
            "bot.runtime_killswitch_authority_liveness_patch": v140,
            "bot.readiness_killswitch_durability_v132_patch": v132,
        }
        original_import = mod.importlib.import_module
        mod.importlib.import_module = lambda name: modules[name] if name in modules else original_import(name)
        try:
            self.assertFalse(mod._post_reassert_recheck())
        finally:
            mod.importlib.import_module = original_import
        self.assertEqual(calls, ["attempt"])

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

        singleton = FakeKillSwitch()

        def base_causal(status):
            history = list(status.get("recent_history") or [])
            latest = history[-1] if history else {}
            return str(latest.get("reason") or ""), str(latest.get("source") or "")

        v140 = types.SimpleNamespace(_causal_activation=base_causal)
        v131 = types.SimpleNamespace(_causal_activation=base_causal)
        v130 = types.SimpleNamespace(_latest_activation=base_causal)
        v132 = types.SimpleNamespace(_attempt_persisted_stop_recovery=lambda: False)
        manifest = types.SimpleNamespace(_REQUIRED_FLAGS={}, _INSTALLERS=tuple(), DECLARED_RELEASE_ID="old", RELEASE_ID="old")
        kill_module = types.SimpleNamespace(KillSwitch=FakeKillSwitch, get_kill_switch=lambda: singleton)
        modules = {
            "bot.kill_switch": kill_module,
            "bot.runtime_killswitch_authority_liveness_patch": v140,
            "bot.readiness_killswitch_causality_v131_patch": v131,
            "bot.kill_switch_stale_heartbeat_recovery_v130_patch": v130,
            "bot.readiness_killswitch_durability_v132_patch": v132,
            "bot.runtime_release_manifest_patch": manifest,
        }

        original_import = mod.importlib.import_module
        original_installed = mod._INSTALLED
        tracked_envs = {
            name: os.environ.get(name)
            for name in (
                mod._FLAG,
                mod._REASSERT_FLAG,
                mod._POST_REASSERT_FLAG,
                "NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY",
                "NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY",
            )
        }
        mod.importlib.import_module = lambda name: modules[name] if name in modules else original_import(name)
        os.environ["NIJA_RUNTIME_KILLSWITCH_AUTHORITY_LIVENESS_V140_READY"] = "1"
        os.environ["NIJA_CAPITAL_PUBLICATION_LIVENESS_V142_READY"] = "1"
        mod._INSTALLED = False
        try:
            self.assertTrue(mod.install_import_hook())
            first_status_owner = FakeKillSwitch.get_status
            self.assertTrue(getattr(first_status_owner, mod._PATCH_ATTR, False))
            self.assertTrue(getattr(v140._causal_activation, mod._PATCH_ATTR, False))
            self.assertTrue(getattr(v131._causal_activation, mod._PATCH_ATTR, False))

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
            self.assertEqual(os.environ.get(mod._POST_REASSERT_FLAG), "1")
            self.assertEqual(
                manifest._REQUIRED_FLAGS.get("kill_switch_post_reassert_recheck_v186"),
                mod._POST_REASSERT_FLAG,
            )

            status = FakeKillSwitch().get_status()
            self.assertEqual(status[mod._META_KEY].get("reason"), HEARTBEAT)
            reason, source = v140._causal_activation(status)
            self.assertEqual(reason, HEARTBEAT)
            self.assertEqual(source, "AUTOMATIC")
        finally:
            mod.importlib.import_module = original_import
            mod._INSTALLED = original_installed
            for name, value in tracked_envs.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
