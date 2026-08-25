"""Regression tests for runtime authority/nonce truth convergence v231."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bot.runtime_authority_nonce_truth_convergence_v231_patch as v231


class _FakeReadiness:
    def __init__(self, table=None):
        self.table = dict(table or {})
        self.revocations = []

    def snapshot(self):
        return dict(self.table)

    def mark_ready(self, key):
        self.table[key] = True

    def revoke_ready(self, key, reason=""):
        self.table[key] = False
        self.revocations.append((key, reason))


class AuthorityNonceTruthV231Tests(unittest.TestCase):
    def test_collect_keeps_current_authority_true_while_nonce_is_pending(self) -> None:
        def original_collect():
            return (
                {
                    "authority_ready": False,
                    "nonce_ready": False,
                    "execution_ready": False,
                    "risk_ready": True,
                },
                {"execution_pipeline_wired": True},
            )

        fake_v16 = SimpleNamespace(_collect_proofs=original_collect)
        with patch.object(v231, "_v16", return_value=fake_v16), \
             patch.object(v231, "_current_writer_authority_proof", return_value=(True, "current")), \
             patch.object(v231, "_kraken_nonce_required", return_value=True):
            self.assertTrue(v231._patch_v16_proof_collection())
            proofs, details = fake_v16._collect_proofs()

        self.assertTrue(proofs["authority_ready"])
        self.assertFalse(proofs["nonce_ready"])
        self.assertFalse(proofs["execution_ready"])
        self.assertTrue(details["v231_kraken_nonce_required"])

    def test_execution_requires_both_authority_and_nonce(self) -> None:
        def original_collect():
            return (
                {
                    "authority_ready": False,
                    "nonce_ready": True,
                    "execution_ready": False,
                    "risk_ready": True,
                },
                {"execution_pipeline_wired": True},
            )

        fake_v16 = SimpleNamespace(_collect_proofs=original_collect)
        with patch.object(v231, "_v16", return_value=fake_v16), \
             patch.object(v231, "_current_writer_authority_proof", return_value=(True, "current")), \
             patch.object(v231, "_kraken_nonce_required", return_value=True):
            self.assertTrue(v231._patch_v16_proof_collection())
            proofs, _ = fake_v16._collect_proofs()

        self.assertTrue(proofs["authority_ready"])
        self.assertTrue(proofs["nonce_ready"])
        self.assertTrue(proofs["execution_ready"])

    def test_active_kraken_revokes_false_coinbase_nonce_shortcut(self) -> None:
        readiness = _FakeReadiness({"nonce_ready": True})
        fake_v16 = SimpleNamespace(
            _collect_proofs=lambda: ({"nonce_ready": False}, {})
        )
        with patch.object(v231, "_kraken_nonce_required", return_value=True), \
             patch.object(v231, "_readiness", return_value=readiness), \
             patch.object(v231, "_v16", return_value=fake_v16):
            ok, detail = v231._correct_heartbeat_nonce_truth()

        self.assertFalse(ok)
        self.assertEqual(detail, "kraken_nonce_current_proof_false")
        self.assertFalse(readiness.table["nonce_ready"])
        self.assertEqual(
            readiness.revocations,
            [("nonce_ready", "v231_active_kraken_nonce_proof_false")],
        )

    def test_no_kraken_leaves_nonce_not_applicable(self) -> None:
        readiness = _FakeReadiness({"nonce_ready": False})
        with patch.object(v231, "_kraken_nonce_required", return_value=False), \
             patch.object(v231, "_readiness", return_value=readiness):
            ok, detail = v231._correct_heartbeat_nonce_truth()
        self.assertTrue(ok)
        self.assertEqual(detail, "kraken_nonce_not_applicable")
        self.assertFalse(readiness.table["nonce_ready"])

    def test_position_sync_wakeup_dispatches_existing_v161_monitor_only(self) -> None:
        readiness = _FakeReadiness({"position_sync_ready": False})
        iteration = Mock(return_value=(1, True))
        fake_v161 = SimpleNamespace(_position_monitor_iteration=iteration)

        real_import = v231.importlib.import_module

        def import_side_effect(name):
            if name == "bot.runtime_capital_position_convergence_v161_patch":
                return fake_v161
            return real_import(name)

        with patch.object(v231, "_readiness", return_value=readiness), \
             patch.object(v231.importlib, "import_module", side_effect=import_side_effect):
            self.assertTrue(v231._wake_position_sync_if_needed())

        iteration.assert_called_once_with()
        self.assertFalse(readiness.table["position_sync_ready"])


if __name__ == "__main__":
    unittest.main()
