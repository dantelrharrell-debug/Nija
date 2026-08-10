import unittest

from bot.broker_manager import KrakenBroker


class TestKrakenBalanceCooldown(unittest.TestCase):
    def _build_broker(self) -> KrakenBroker:
        broker = KrakenBroker.__new__(KrakenBroker)
        broker.api = object()
        broker._gateway_url = ""
        broker.account_identifier = "PLATFORM"
        broker.last_connection_error = None
        broker.connected = True
        broker._connection_already_complete = True
        broker._last_known_balance = 321.0
        broker._balance_last_updated = None
        broker._kraken_balance_cache_ttl = 0
        broker.balance_cache = {"kraken": 321.0}
        broker._balance_fetch_errors = 0
        broker._is_available = True
        broker.exit_only_mode = False
        broker.kraken_health = "UNKNOWN"
        return broker

    def test_writer_authority_loss_demotes_stale_connection_immediately(self) -> None:
        broker = self._build_broker()
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "DistributedNonceManager.get_nonce: Redis nonce issuance failed "
                "(Canonical process writer authority unavailable for Kraken nonce lease)"
            )
        )

        balance = broker.get_account_balance(verbose=False)

        self.assertEqual(balance, 0.0)
        self.assertFalse(broker.connected)
        self.assertFalse(broker._connection_already_complete)
        self.assertFalse(broker.is_available())
        self.assertTrue(broker.exit_only_mode)
        self.assertEqual(broker.kraken_health, "ERROR")
        self.assertIn("WRITER_AUTHORITY_UNAVAILABLE", broker.last_connection_error)

    def test_detailed_writer_authority_loss_reports_error_and_demotes(self) -> None:
        broker = self._build_broker()
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "Canonical process writer authority unavailable for Kraken nonce lease"
            )
        )

        detailed = broker.get_account_balance_detailed(verbose=False)

        self.assertTrue(detailed["error"])
        self.assertFalse(broker.connected)
        self.assertFalse(broker._connection_already_complete)
        self.assertFalse(broker.is_available())

    def test_balance_fetch_does_not_count_retry_suppressed_nonce_rebuilds(self) -> None:
        broker = self._build_broker()
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
                "retry suppressed for 29.0s cooldown."
            )
        )

        balance = broker.get_account_balance(verbose=False)

        self.assertEqual(balance, 321.0)
        self.assertEqual(broker.get_error_count(), 0)
        self.assertTrue(broker.is_available())
        self.assertFalse(broker.exit_only_mode)

    def test_balance_fetch_does_not_count_initial_nonce_rebuild_failure_cooldown(self) -> None:
        broker = self._build_broker()
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "KrakenNonceManager singleton was destroyed and rebuild failed; "
                "retry cooldown 30.0s activated."
            )
        )

        balance = broker.get_account_balance(verbose=False)

        self.assertEqual(balance, 321.0)
        self.assertEqual(broker.get_error_count(), 0)
        self.assertTrue(broker.is_available())
        self.assertFalse(broker.exit_only_mode)
        self.assertIn("api connectivity or credentials", broker.last_connection_error.lower())

    def test_balance_fetch_clears_stale_offline_state_during_cooldown_recovery(self) -> None:
        broker = self._build_broker()
        broker._balance_fetch_errors = 12
        broker._is_available = False
        broker.exit_only_mode = True
        broker.kraken_health = "ERROR"
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "KrakenNonceManager singleton was destroyed and previous rebuild failed; "
                "retry suppressed for 29.0s cooldown."
            )
        )

        balance = broker.get_account_balance(verbose=False)

        self.assertEqual(balance, 321.0)
        self.assertEqual(broker.get_error_count(), 0)
        self.assertTrue(broker.is_available())
        self.assertFalse(broker.exit_only_mode)
        self.assertEqual(broker.kraken_health, "OK")

    def test_detailed_balance_uses_cached_balance_during_cooldown_recovery(self) -> None:
        broker = self._build_broker()
        broker._balance_fetch_errors = 7
        broker._is_available = False
        broker.exit_only_mode = True
        broker.kraken_health = "ERROR"
        broker._kraken_private_call = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "KrakenNonceManager singleton was destroyed and rebuild failed; "
                "retry cooldown 30.0s activated."
            )
        )

        detailed = broker.get_account_balance_detailed(verbose=False)

        self.assertFalse(detailed["error"])
        self.assertEqual(detailed["trading_balance"], 321.0)
        self.assertEqual(detailed["total_funds"], 321.0)
        self.assertEqual(broker.get_error_count(), 0)
        self.assertTrue(broker.is_available())
        self.assertFalse(broker.exit_only_mode)
        self.assertEqual(broker.kraken_health, "OK")


if __name__ == "__main__":
    unittest.main()
