import unittest
from bot.kraken_risk_snapshot_diagnostic_v490 import inspect_risk_snapshot

VALID = {
    "halt_active": False, "halt_reason": "none",
    "open_positions": 1, "total_risk_usd": 2.0,
    "config": {"max_daily_loss_pct": 3.0, "max_total_risk_pct": 10.0,
               "max_open_positions": 3, "max_consecutive_losses": 4},
}

class RiskSnapshotDiagnosticTests(unittest.TestCase):
    def test_valid_is_diagnostic_only(self):
        result = inspect_risk_snapshot(VALID)
        self.assertTrue(result["ready"])
        self.assertFalse(result["authorizes_orders"])
        self.assertFalse(result["independent_certification"])

    def test_missing_snapshot_fails_closed(self):
        self.assertFalse(inspect_risk_snapshot(None)["ready"])

    def test_halt_fails_closed(self):
        self.assertFalse(inspect_risk_snapshot({**VALID, "halt_active": True})["ready"])

    def test_limit_exceeded(self):
        self.assertFalse(inspect_risk_snapshot({**VALID, "open_positions": 4})["ready"])

    def test_invalid_limit(self):
        self.assertFalse(inspect_risk_snapshot({**VALID, "config": {**VALID["config"], "max_total_risk_pct": float("nan")}})["ready"])

if __name__ == "__main__":
    unittest.main()
