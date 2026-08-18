from __future__ import annotations

import importlib
import os
import unittest


class RuntimeManifestV145OwnershipV146Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = importlib.import_module("bot.runtime_release_manifest_patch")

    def test_manifest_installs_v145_directly(self) -> None:
        self.assertIn(
            ("bot.runtime_startup_convergence_v145_patch", "install_import_hook"),
            tuple(self.manifest._INSTALLERS),
        )

    def test_manifest_requires_v145_ready_proof(self) -> None:
        self.assertEqual(
            self.manifest._REQUIRED_FLAGS.get("runtime_startup_convergence_v145"),
            "NIJA_RUNTIME_STARTUP_CONVERGENCE_V145_READY",
        )

    def test_missing_v145_proof_cannot_publish_ready(self) -> None:
        required = dict(self.manifest._REQUIRED_FLAGS)
        installers = tuple(self.manifest._INSTALLERS)
        original_invoke = self.manifest._invoke
        original_scan_release = self.manifest._expected_scan_wrapper_release
        original_scan_compatible = self.manifest._scan_release_compatible
        original_limits = self.manifest._runtime_limits_consistent
        original_contract = self.manifest._readiness_contract_consistent
        original_import = self.manifest.importlib.import_module
        env_backup = dict(os.environ)
        try:
            for flag in required.values():
                os.environ[flag] = "1"
            os.environ.pop("NIJA_RUNTIME_STARTUP_CONVERGENCE_V145_READY", None)
            os.environ["NIJA_SCAN_WRAPPER_RELEASE"] = "test-release"

            self.manifest._invoke = lambda *_args, **_kwargs: (True, "ok")
            self.manifest._expected_scan_wrapper_release = lambda: "test-release"
            self.manifest._scan_release_compatible = lambda actual, expected: actual == expected
            self.manifest._runtime_limits_consistent = lambda: (True, "ok")
            self.manifest._readiness_contract_consistent = lambda: (True, "ok")

            class _AuditModule:
                @staticmethod
                def audit():
                    return True, "ok"

            def _fake_import(name: str):
                if name in {
                    "runtime_module_identity_convergence_patch",
                    "runtime_convergence_quiescence_patch",
                    "scan_wrapper_depth_convergence_patch",
                }:
                    return _AuditModule()
                return original_import(name)

            self.manifest.importlib.import_module = _fake_import
            ready, details = self.manifest._audit()
            self.assertFalse(ready)
            self.assertEqual(details["runtime_startup_convergence_v145"], "missing")
        finally:
            self.manifest._invoke = original_invoke
            self.manifest._expected_scan_wrapper_release = original_scan_release
            self.manifest._scan_release_compatible = original_scan_compatible
            self.manifest._runtime_limits_consistent = original_limits
            self.manifest._readiness_contract_consistent = original_contract
            self.manifest.importlib.import_module = original_import
            os.environ.clear()
            os.environ.update(env_backup)
            self.manifest._INSTALLERS = installers
            self.manifest._REQUIRED_FLAGS = required


if __name__ == "__main__":
    unittest.main()
