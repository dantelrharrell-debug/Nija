"""Isolated account-cell policy tests. No broker network calls."""
import unittest

from bot.member_broker_cells import CellChecks, CellKey, CellState, cell_state, isolation_report


class CellPolicyTests(unittest.TestCase):
    def setUp(self):
        self.a = CellKey("member_a", "kraken", "live", "account_a")
        self.b = CellKey("member_b", "alpaca", "live", "account_b")
        self.good = CellChecks(True, True, True, True, True, True, True, True)

    def test_cell_ids_include_member_broker_environment_and_account(self):
        self.assertNotEqual(self.a.isolation_id, self.b.isolation_id)
        self.assertNotEqual(self.a.isolation_id, CellKey("member_a", "kraken", "paper", "account_a").isolation_id)
        self.assertNotEqual(self.a.isolation_id, CellKey("member_a", "kraken", "live", "other_account").isolation_id)

    def test_unhealthy_member_does_not_block_other_cell(self):
        broken = CellChecks(True, True, True, False, True, True, True, True)
        report = isolation_report({self.a: broken, self.b: self.good}, global_emergency_stop=False)
        self.assertEqual(report[self.a], CellState.BLOCKED)
        self.assertEqual(report[self.b], CellState.READY)

    def test_global_emergency_stop_disables_every_cell(self):
        report = isolation_report({self.a: self.good, self.b: self.good}, global_emergency_stop=True)
        self.assertTrue(all(state is CellState.DISABLED for state in report.values()))

    def test_no_live_without_protection_or_proof(self):
        missing_exit = CellChecks(True, True, True, True, False, True, True, True)
        missing_proof = CellChecks(True, True, True, True, True, True, False, True)
        self.assertEqual(cell_state(self.a, missing_exit, global_emergency_stop=False), CellState.BLOCKED)
        self.assertEqual(cell_state(self.a, missing_proof, global_emergency_stop=False), CellState.BLOCKED)

    def test_invalid_broker_and_unbound_account_fail(self):
        with self.assertRaises(ValueError):
            CellKey("member", "coinbase", "live", "account")
        with self.assertRaises(ValueError):
            CellKey("member", "kraken", "live", "")


if __name__ == "__main__":
    unittest.main()
