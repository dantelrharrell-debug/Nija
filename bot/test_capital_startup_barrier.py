import unittest

from bot.broker_manager import AccountType, BaseBroker, BrokerType
from bot.multi_account_broker_manager import (
    MultiAccountBrokerManager,
    get_broker_manager,
    reset_broker_manager_singleton,
)


class _MockBroker(BaseBroker):
    def __init__(
        self,
        broker_type: BrokerType = BrokerType.KRAKEN,
        connected: bool = True,
        ready_for_capital: bool = True,
        has_payload: bool = True,
        balance: float = 100.0,
    ) -> None:
        super().__init__(broker_type, account_type=AccountType.PLATFORM)
        self.connected = connected
        self._ready_for_capital = ready_for_capital
        self._has_payload = has_payload
        self._balance = balance

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return self._balance

    def get_positions(self):
        return []

    def place_market_order(self, symbol, side, quantity, size_type='quote',
                           ignore_balance=False, ignore_min_trade=False, force_liquidate=False):
        return {"status": "filled"}

    def is_ready_for_capital(self) -> bool:
        return bool(self._ready_for_capital)

    def has_balance_payload(self) -> bool:
        return bool(self._has_payload)


class TestCapitalStartupBarrier(unittest.TestCase):
    def tearDown(self):
        reset_broker_manager_singleton()

    def test_pending_when_no_registered_sources(self):
        manager = get_broker_manager()
        snapshot = manager.refresh_capital_authority(trigger="platform_connect:kraken:attempt_1")

        self.assertEqual(snapshot.get("ready"), 0.0)
        self.assertEqual(snapshot.get("total_capital"), 0.0)
        self.assertEqual(snapshot.get("pending"), 1.0)

    def test_pending_when_registered_but_not_eligible(self):
        manager = get_broker_manager()
        broker = _MockBroker(ready_for_capital=False, has_payload=False, connected=False)
        manager.register_platform_broker_instance(BrokerType.KRAKEN, broker, mark_connected_state=False)

        snapshot = manager.refresh_capital_authority(trigger="platform_connect:kraken:attempt_1")

        self.assertEqual(snapshot.get("ready"), 0.0)
        self.assertEqual(snapshot.get("total_capital"), 0.0)
        self.assertEqual(snapshot.get("pending"), 1.0)

    def test_bootstrap_connected_kraken_contributes_nonzero_capital(self):
        manager = get_broker_manager()
        broker = _MockBroker(
            broker_type=BrokerType.KRAKEN,
            connected=True,
            ready_for_capital=True,
            has_payload=True,
            balance=250.0,
        )
        manager.register_platform_broker_instance(BrokerType.KRAKEN, broker, mark_connected_state=False)

        snapshot = manager.refresh_capital_authority(trigger="platform_connect:kraken:attempt_1")

        self.assertGreaterEqual(snapshot.get("valid_brokers", 0.0), 1.0)
        self.assertGreater(snapshot.get("total_capital", 0.0), 0.0)
        self.assertGreater(snapshot.get("kraken_capital", 0.0), 0.0)

    def test_coinbase_and_kraken_balances_are_both_counted(self):
        manager = get_broker_manager()
        kraken = _MockBroker(
            broker_type=BrokerType.KRAKEN,
            connected=True,
            ready_for_capital=True,
            has_payload=True,
            balance=103.98,
        )
        coinbase = _MockBroker(
            broker_type=BrokerType.COINBASE,
            connected=True,
            ready_for_capital=True,
            has_payload=True,
            balance=10.31,
        )
        manager.register_platform_broker_instance(BrokerType.KRAKEN, kraken, mark_connected_state=False)
        manager.register_platform_broker_instance(BrokerType.COINBASE, coinbase, mark_connected_state=False)

        snapshot = manager.refresh_capital_authority(trigger="initialize_platform_brokers:attempt_1")

        self.assertEqual(snapshot.get("ready"), 1.0)
        self.assertGreaterEqual(snapshot.get("valid_brokers", 0.0), 2.0)
        self.assertAlmostEqual(snapshot.get("kraken_capital", 0.0), 103.98, places=2)
        self.assertAlmostEqual(snapshot.get("total_capital", 0.0), 114.29, places=2)

    def test_has_registered_sources_requires_primary_registration_pipeline(self):
        manager = get_broker_manager()
        broker = _MockBroker()
        self.assertFalse(manager.has_registered_sources())

        manager._platform_brokers[BrokerType.KRAKEN] = broker
        manager.refresh_registry()
        self.assertFalse(manager.has_registered_sources())

        manager.register_platform_broker_instance(BrokerType.COINBASE, _MockBroker(BrokerType.COINBASE))
        self.assertTrue(manager.has_registered_sources())

    def test_registration_redirects_to_canonical_instance(self):
        canonical = get_broker_manager()
        self.assertIs(canonical, get_broker_manager())

        non_canonical = MultiAccountBrokerManager()
        registered = non_canonical.register_platform_broker_instance(
            BrokerType.KRAKEN, _MockBroker()
        )
        self.assertTrue(registered)
        self.assertIn(BrokerType.KRAKEN, canonical._platform_brokers)
        self.assertNotIn(BrokerType.KRAKEN, non_canonical._platform_brokers)


if __name__ == "__main__":
    unittest.main()
