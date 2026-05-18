import unittest
from types import SimpleNamespace

from bot.broker_manager import BrokerType
from bot.multi_account_broker_manager import MultiAccountBrokerManager


class TestPlatformBrokerStatusClassification(unittest.TestCase):
    def test_connected_broker_reports_connected(self) -> None:
        broker = SimpleNamespace(connected=True)
        status = MultiAccountBrokerManager._format_platform_broker_status(
            BrokerType.COINBASE,
            broker,
        )
        self.assertEqual(status, "✅ CONNECTED")

    def test_kraken_cooldown_recovery_reports_recovery_status(self) -> None:
        broker = SimpleNamespace(
            connected=False,
            last_connection_error=(
                "Kraken nonce-manager rebuild recovery active; "
                "investigate Kraken API connectivity or credentials"
            ),
            _last_known_balance=321.0,
            balance_cache={},
        )
        status = MultiAccountBrokerManager._format_platform_broker_status(
            BrokerType.KRAKEN,
            broker,
            include_primary_suffix=True,
        )
        self.assertEqual(
            status,
            "⚠️ COOLDOWN RECOVERY (cached balance active — entries blocked)",
        )

    def test_kraken_without_cached_balance_stays_not_connected(self) -> None:
        broker = SimpleNamespace(
            connected=False,
            last_connection_error=(
                "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
                "retry suppressed for 29.0s cooldown."
            ),
            _last_known_balance=None,
            balance_cache={},
        )
        status = MultiAccountBrokerManager._format_platform_broker_status(
            BrokerType.KRAKEN,
            broker,
        )
        self.assertEqual(status, "❌ NOT CONNECTED")


if __name__ == "__main__":
    unittest.main()
