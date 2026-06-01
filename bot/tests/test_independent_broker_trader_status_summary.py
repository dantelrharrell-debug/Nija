import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from bot.independent_broker_trader import IndependentBrokerTrader


class TestIndependentBrokerTraderStatusSummary(unittest.TestCase):
    def setUp(self) -> None:
        self.trader = IndependentBrokerTrader(
            broker_manager=SimpleNamespace(brokers={"kraken": SimpleNamespace(connected=True)}),
            trading_strategy=SimpleNamespace(),
        )

    def test_summary_flags_active_users_when_platform_idle(self) -> None:
        now = datetime.now()
        self.trader.broker_health["kraken"] = {
            "status": "degraded",
            "is_trading": False,
            "last_check": now,
        }
        self.trader.user_broker_health["alice"] = {
            "alice_kraken": {
                "status": "healthy",
                "is_trading": True,
                "last_check": now,
            }
        }

        summary = self.trader.get_status_summary()
        alignment = summary["activity_alignment"]

        self.assertTrue(alignment["users_active_while_platform_idle"])
        self.assertEqual(alignment["active_user_account_count"], 1)
        self.assertEqual(alignment["active_user_broker_count"], 1)
        self.assertEqual(alignment["active_platform_broker_count"], 0)

    def test_summary_clears_flag_when_platform_is_recently_active(self) -> None:
        now = datetime.now()
        self.trader.broker_health["kraken"] = {
            "status": "healthy",
            "is_trading": True,
            "last_check": now,
        }
        self.trader.user_broker_health["alice"] = {
            "alice_kraken": {
                "status": "healthy",
                "is_trading": True,
                "last_check": now,
            }
        }

        summary = self.trader.get_status_summary()
        alignment = summary["activity_alignment"]

        self.assertFalse(alignment["users_active_while_platform_idle"])
        self.assertEqual(alignment["active_platform_brokers"], ["kraken"])

    def test_stale_user_activity_does_not_trigger_mismatch(self) -> None:
        stale = datetime.now() - timedelta(seconds=600)
        self.trader.user_broker_health["alice"] = {
            "alice_kraken": {
                "status": "healthy",
                "is_trading": True,
                "last_check": stale,
            }
        }

        summary = self.trader.get_status_summary()
        alignment = summary["activity_alignment"]

        self.assertFalse(alignment["users_active_while_platform_idle"])
        self.assertEqual(alignment["active_user_account_count"], 0)


if __name__ == "__main__":
    unittest.main()
