"""Exercise the actual recovery function without installing runtime hooks."""
from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class CanonicalRecoveryDeferralTests(unittest.TestCase):
    """Canonical hook deferral must not silence owned proof recovery."""

    def _run(self, environment: dict[str, str], prerequisite: bool = True,
             module_ready: bool = True) -> tuple[bool, list[str]]:
        source = Path(__file__).resolve().parents[2] / "bot/production_runtime_convergence_v88_patch.py"
        tree = ast.parse(source.read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_truthy", "_install_critical_kraken_liveness"}]
        calls: list[str] = []

        def importer(name: str, **_kwargs: object) -> SimpleNamespace:
            def install() -> bool:
                calls.append(name)
                return prerequisite if "v318" in name else module_ready
            return SimpleNamespace(install_import_hook=install)

        namespace = {"os": os, "LOGGER": logging.getLogger(__name__),
                     "_TRUE": {"1", "true", "yes", "on", "enabled", "y"},
                     "CRITICAL_LIVENESS_MARKER": "test", "__import__": importer}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        with patch.dict(os.environ, environment, clear=True):
            ready = namespace["_install_critical_kraken_liveness"]()
        return ready, calls

    @staticmethod
    def _canonical() -> dict[str, str]:
        return {"NIJA_DEFER_RUNTIME_SITE_HOOKS": "1",
                "NIJA_CANONICAL_ENTRYPOINT_FAST_PATH": "1",
                "NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY": "1"}

    def test_canonical_deferred_fanout_runs_owned_recovery(self) -> None:
        ready, calls = self._run(self._canonical())
        self.assertTrue(ready)
        self.assertEqual(len(calls), 6)
        self.assertIn("v318", calls[0])
        self.assertTrue(any("v286" in name for name in calls))

    def test_ci_and_pytest_stay_isolated_with_launcher_flags(self) -> None:
        for marker in ({"CI": "true"}, {"PYTEST_CURRENT_TEST": "fixture"}):
            with self.subTest(marker=marker):
                ready, calls = self._run({**self._canonical(), **marker})
                self.assertFalse(ready)
                self.assertEqual(calls, [])

    def test_incomplete_launcher_handoff_stays_deferred(self) -> None:
        for missing in ("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH",
                        "NIJA_CANONICAL_RUNTIME_LAUNCHER_V26_READY"):
            with self.subTest(missing=missing):
                environment = self._canonical()
                environment.pop(missing)
                self.assertEqual(self._run(environment), (False, []))

    def test_prerequisite_and_pending_proof_are_not_promoted(self) -> None:
        ready, calls = self._run(self._canonical(), prerequisite=False)
        self.assertFalse(ready)
        self.assertEqual(len(calls), 1)
        ready, calls = self._run(self._canonical(), module_ready=False)
        self.assertFalse(ready)
        self.assertEqual(len(calls), 6)


if __name__ == "__main__":
    unittest.main()
