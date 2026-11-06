"""Mandatory one-shot commissioning authorization invariants.

These tests never construct a live broker or dispatch an order.
"""
import unittest
from bot.startup_two_phase_policy_v8 import PREFLIGHT, evaluate_startup_transition


class CommissioningSingleFlightPolicyTests(unittest.TestCase):
    def test_ready_pretrade_is_not_dispatch_authorization(self):
        result = evaluate_startup_transition(
            {field: True for field in PREFLIGHT},
            pending_execution=False,
            posttrade_verified=False,
        )
        self.assertTrue(result["pretrade_candidate_ready"])
        self.assertFalse(result["activation_allowed"])

    def test_pending_unverified_order_never_grants_authority(self):
        result = evaluate_startup_transition(
            {field: True for field in PREFLIGHT},
            pending_execution=True,
            posttrade_verified=False,
        )
        self.assertFalse(result["pretrade_candidate_ready"])
        self.assertFalse(result["activation_allowed"])
        self.assertTrue(result["posttrade_verification_required"])


if __name__ == "__main__":
    unittest.main()
