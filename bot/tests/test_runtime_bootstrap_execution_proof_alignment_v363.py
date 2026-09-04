from __future__ import annotations

import importlib
import threading
import types
import unittest
from unittest import mock


class _FakeBootstrapFSM:
    def __init__(self, raw_authority: bool) -> None:
        self._lock = threading.Lock()
        self._execution_authority = raw_authority


class RuntimeBootstrapExecutionProofAlignmentV363Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = importlib.import_module(
            "bot.runtime_bootstrap_execution_proof_alignment_v363_patch"
        )

    def test_raw_bootstrap_authority_is_not_effective_without_canonical_proof(self) -> None:
        fsm = _FakeBootstrapFSM(True)
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ):
            ready, detail = self.patch._effective_bootstrap_authority(fsm)

        self.assertFalse(ready)
        self.assertEqual(detail, "canonical_execution_proof_pending")
        self.assertTrue(fsm._execution_authority)

    def test_raw_bootstrap_authority_becomes_effective_only_with_canonical_proof(self) -> None:
        fsm = _FakeBootstrapFSM(True)
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(True, "canonical_execution_ready"),
        ):
            ready, detail = self.patch._effective_bootstrap_authority(fsm)

        self.assertTrue(ready)
        self.assertEqual(detail, "bootstrap_and_canonical_execution_ready")

    def test_missing_raw_bootstrap_authority_stays_false_even_with_canonical_proof(self) -> None:
        fsm = _FakeBootstrapFSM(False)
        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(True, "canonical_execution_ready"),
        ):
            ready, detail = self.patch._effective_bootstrap_authority(fsm)

        self.assertFalse(ready)
        self.assertEqual(detail, "bootstrap_execution_authority_false")

    def test_execution_contract_authority_is_gated_before_legacy_repair(self) -> None:
        calls = {"original": 0}

        def original() -> tuple[bool, str]:
            calls["original"] += 1
            return True, "legacy_authority"

        fake_module = types.SimpleNamespace(authority_proof=original)
        real_import = importlib.import_module

        def fake_import(name: str):
            if name == "bot.execution_contract_authority":
                return fake_module
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import):
            self.assertTrue(self.patch._patch_execution_contract_authority())

        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(False, "canonical_execution_proof_pending"),
        ):
            ready, detail = fake_module.authority_proof()

        self.assertFalse(ready)
        self.assertEqual(detail, "canonical_execution_proof_pending")
        self.assertEqual(calls["original"], 0)

    def test_execution_contract_legacy_checks_still_run_after_genuine_proof(self) -> None:
        calls = {"original": 0}

        def original() -> tuple[bool, str]:
            calls["original"] += 1
            return True, "legacy_authority"

        fake_module = types.SimpleNamespace(authority_proof=original)
        real_import = importlib.import_module

        def fake_import(name: str):
            if name == "bot.execution_contract_authority":
                return fake_module
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import):
            self.assertTrue(self.patch._patch_execution_contract_authority())

        with mock.patch.object(
            self.patch,
            "_canonical_execution_ready",
            return_value=(True, "canonical_execution_ready"),
        ):
            ready, detail = fake_module.authority_proof()

        self.assertTrue(ready)
        self.assertEqual(detail, "legacy_authority")
        self.assertEqual(calls["original"], 1)


if __name__ == "__main__":
    unittest.main()
