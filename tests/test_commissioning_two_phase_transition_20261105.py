"""Mandatory two-phase commissioning policy regressions.

No collector, broker, or dispatch is installed by these tests.
"""
import unittest

from bot.startup_two_phase_policy_v8 import PREFLIGHT, evaluate_startup_transition


class TwoPhaseTransitionTests(unittest.TestCase):
    def test_cold_start_can_be_pretrade_candidate_but_never_authorizes_orders(self):
        facts = {field: True for field in PREFLIGHT}
        result = evaluate_startup_transition(
            facts, pending_execution=False, posttrade_verified=False,
        )
        self.assertTrue(result["pretrade_candidate_ready"])
        self.assertFalse(result["activation_allowed"])
        self.assertTrue(result["diagnostic_only"])
        self.assertTrue(result["legacy_execution_gate_unchanged"])

    def test_pending_execution_requires_posttrade_proof(self):
        facts = {field: True for field in PREFLIGHT}
        result = evaluate_startup_transition(
            facts, pending_execution=True, posttrade_verified=False,
        )
        self.assertFalse(result["pretrade_candidate_ready"])
        self.assertIn("posttrade_execution_proof", result["missing"])
        self.assertFalse(result["activation_allowed"])

    def test_missing_independent_certificate_denies_candidate(self):
        facts = {field: True for field in PREFLIGHT}
        facts["authenticated_pretrade_certificate"] = False
        result = evaluate_startup_transition(
            facts, pending_execution=False, posttrade_verified=False,
        )
        self.assertFalse(result["pretrade_candidate_ready"])
        self.assertIn("authenticated_pretrade_certificate", result["missing"])

    def test_invalid_execution_state_denied(self):
        facts = {field: True for field in PREFLIGHT}
        result = evaluate_startup_transition(
            facts, pending_execution=1, posttrade_verified=False,
        )
        self.assertFalse(result["pretrade_candidate_ready"])
        self.assertIn("execution_state_invalid", result["missing"])


if __name__ == "__main__":
    unittest.main()
