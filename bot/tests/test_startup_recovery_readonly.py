"""Offline recovery classifications: no broker calls or order side effects."""
import unittest
from bot.startup_recovery_readonly import classify_recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.ready = {key: True for key in (
            "broker_connected", "authority_ready", "capital_ready",
            "risk_ready", "strategy_ready", "nonce_ready",
            "position_sync_ready", "execution_ready")}

    def classify(self, readiness=None, **overrides):
        flags = dict(kill_switch_clear=True, startup_attempts_reconciled=True,
                     protective_exits_verified=True, ledger_reconciled=True)
        flags.update(overrides)
        return classify_recovery(self.ready if readiness is None else readiness, **flags)

    def test_fully_verified_never_authorizes_orders(self):
        result = self.classify()
        self.assertEqual(result.state, "VERIFICATION_COMPLETE")
        self.assertTrue(result.allow_readonly_checks)
        self.assertFalse(result.allow_new_orders)

    def test_stale_proof_allows_readonly_but_not_trading(self):
        readiness = dict(self.ready, execution_ready=False)
        result = self.classify(readiness)
        self.assertEqual(result.state, "READ_ONLY_RECOVERY")
        self.assertIn("execution_ready", result.reasons)
        self.assertFalse(result.allow_new_orders)

    def test_unreconciled_and_unsafe_conditions_never_authorize(self):
        result = self.classify(self.ready, kill_switch_clear=False,
                               startup_attempts_reconciled=False,
                               protective_exits_verified=False,
                               ledger_reconciled=False)
        self.assertIn("kill_switch", result.reasons)
        self.assertIn("startup_attempts", result.reasons)
        self.assertIn("protective_exits", result.reasons)
        self.assertIn("ledger", result.reasons)
        self.assertFalse(result.allow_new_orders)

    def test_disconnected_fails_closed(self):
        result = self.classify(dict(self.ready, broker_connected=False))
        self.assertEqual(result.state, "DISCONNECTED")
        self.assertFalse(result.allow_readonly_checks)
        self.assertFalse(result.allow_new_orders)


if __name__ == "__main__":
    unittest.main()
