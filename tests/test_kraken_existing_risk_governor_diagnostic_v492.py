import unittest
from bot.kraken_existing_risk_governor_diagnostic_v492 import inspect_existing_risk_governor


class Governor:
    def __init__(self, snapshot):
        self.snapshot = snapshot
    def get_status(self):
        return self.snapshot


VALID = {
    "halt_active": False, "halt_reason": "none",
    "open_positions": 0, "consecutive_losses": 0,
    "config": {"max_daily_loss_pct": 5.0, "max_consecutive_losses": 5,
               "max_open_positions": 12, "max_total_risk_pct": 25.0},
}


class GovernorDiagnosticTests(unittest.TestCase):
    def test_healthy_snapshot_still_non_authorizing(self):
        result = inspect_existing_risk_governor(Governor(VALID))
        self.assertTrue(result["ready"])
        self.assertFalse(result["authorizes_orders"])
        self.assertFalse(result["independent_certification"])

    def test_halt_fails_closed(self):
        result = inspect_existing_risk_governor(Governor({**VALID, "halt_active": True}))
        self.assertFalse(result["ready"])

    def test_missing_config_fails_closed(self):
        result = inspect_existing_risk_governor(Governor({**VALID, "config": {}}))
        self.assertFalse(result["ready"])

    def test_no_governor_fails_closed(self):
        self.assertFalse(inspect_existing_risk_governor(None)["ready"])


if __name__ == "__main__":
    unittest.main()
