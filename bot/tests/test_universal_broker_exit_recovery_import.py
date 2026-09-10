import importlib
import unittest
from unittest.mock import patch


class UniversalBrokerExitRecoveryImportTests(unittest.TestCase):
    def test_account_recovery_snapshot_can_import_isolation_module(self):
        mod = importlib.import_module("bot.universal_broker_exit_supervisor_patch")

        class Broker:
            broker_type = "coinbase"

        expected = {
            "in_recovery": True,
            "level": "RECOVERY",
            "drawdown_pct": 1.0,
        }

        with patch("bot.broker_account_isolation_v64_patch.get_account_recovery_snapshot", return_value=expected):
            snapshot = mod._account_recovery_snapshot(Broker())

        self.assertEqual(snapshot, expected)


if __name__ == "__main__":
    unittest.main()
