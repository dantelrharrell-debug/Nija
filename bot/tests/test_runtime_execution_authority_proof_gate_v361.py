from __future__ import annotations

import importlib
import types
import unittest
from unittest import mock


class RuntimeExecutionAuthorityProofGateV361Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = importlib.import_module("bot.runtime_execution_authority_proof_gate_v361_patch")

    def test_canonical_execution_ready_false_is_fail_closed(self) -> None:
        readiness = types.SimpleNamespace(snapshot=lambda: {"execution_ready": False})
        real_import = self.patch.importlib.import_module

        def fake_import(name: str):
            if name == "bot.readiness_table":
                return readiness
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import):
            ready, detail = self.patch._canonical_execution_ready()
        self.assertFalse(ready)
        self.assertEqual(detail, "canonical_execution_proof_pending")

    def test_missing_execution_proof_does_not_call_authority_convergence_path(self) -> None:
        calls: list[tuple[str, object]] = []

        def original(*, trigger: str = "manual", force: bool = False):
            calls.append(("original", trigger))
            return {"original": True}

        fake_three_venue = types.SimpleNamespace(
            reconcile_execution_readiness=original,
            publish_once=lambda force=False: {
                "writer_ready": True,
                "capital_ready": True,
                "ready_venues": ["kraken", "coinbase", "okx"],
            },
        )
        real_import = self.patch.importlib.import_module

        def fake_import(name: str):
            if name == "three_venue_execution_readiness":
                return fake_three_venue
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import), mock.patch.object(
            self.patch, "_canonical_execution_ready", return_value=(False, "canonical_execution_proof_pending")
        ):
            self.assertTrue(self.patch._patch_three_venue_reconcile())
            payload = fake_three_venue.reconcile_execution_readiness(trigger="monitor", force=True)

        self.assertEqual(payload["ready_venues"], ["kraken", "coinbase", "okx"])
        self.assertEqual(calls, [])

    def test_genuine_canonical_execution_proof_preserves_original_convergence(self) -> None:
        calls: list[tuple[str, bool]] = []

        def original(*, trigger: str = "manual", force: bool = False):
            calls.append((trigger, force))
            return {"converged": True}

        fake_three_venue = types.SimpleNamespace(
            reconcile_execution_readiness=original,
            publish_once=lambda force=False: {"unexpected": True},
        )
        real_import = self.patch.importlib.import_module

        def fake_import(name: str):
            if name == "three_venue_execution_readiness":
                return fake_three_venue
            return real_import(name)

        with mock.patch.object(self.patch.importlib, "import_module", side_effect=fake_import), mock.patch.object(
            self.patch, "_canonical_execution_ready", return_value=(True, "canonical_execution_ready")
        ):
            self.assertTrue(self.patch._patch_three_venue_reconcile())
            payload = fake_three_venue.reconcile_execution_readiness(trigger="confirmed_fill", force=True)

        self.assertEqual(payload, {"converged": True})
        self.assertEqual(calls, [("confirmed_fill", True)])


if __name__ == "__main__":
    unittest.main()
