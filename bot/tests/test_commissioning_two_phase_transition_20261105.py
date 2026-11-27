"""Regression checks for the proposed two-phase commissioning transition.

No live admission is granted by this diagnostic policy.
"""
import unittest

from bot.startup_two_phase_policy_v8 import PREFLIGHT, evaluate_startup_transition


class CommissioningTwoPhaseTransitionTests(unittest.TestCase):
    def setUp(self):
        self.facts = {name: True for name in PREFLIGHT}

    def test_cold_start_requires_no_historical_fill(self):
        result = evaluate_startup_transition(
            self.facts, pending_execution=False, posttrade_verified=False
        )
        self.assertTrue(result["pretrade_candidate_ready"])
        self.assertFalse(result["activation_allowed"])
        self.assertTrue(result["diagnostic_only"])

    def test_pending_first_trade_requires_posttrade_proof(self):
        result = evaluate_startup_transition(
            self.facts, pending_execution=True, posttrade_verified=False
        )
        self.assertFalse(result["pretrade_candidate_ready"])
        self.assertIn("posttrade_execution_proof", result["missing"])
        self.assertFalse(result["activation_allowed"])

    def test_missing_safety_fact_fails_closed(self):
        for field in PREFLIGHT:
            with self.subTest(field=field):
                facts = dict(self.facts)
                facts[field] = False
                result = evaluate_startup_transition(
                    facts, pending_execution=False, posttrade_verified=False
                )
                self.assertIn(field, result["missing"])
                self.assertFalse(result["pretrade_candidate_ready"])
                self.assertFalse(result["activation_allowed"])


if __name__ == "__main__":
    unittest.main()
