import unittest

from bot.execution_venue_config import (
    get_preferred_execution_venue,
    should_initialize_coinbase_platform,
)


class ExecutionVenueConfigTests(unittest.TestCase):
    def test_coinbase_platform_allowed_with_kraken_primary(self):
        env = {
            "ENABLE_COINBASE_TRADING": "true",
            "PRIMARY_EXECUTION_VENUE": "kraken",
        }
        self.assertTrue(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_blocked_when_trading_disabled(self):
        env = {"ENABLE_COINBASE_TRADING": "false"}
        self.assertFalse(should_initialize_coinbase_platform(env))

    def test_preferred_execution_venue_forces_single_broker(self):
        env = {"PRIMARY_EXECUTION_VENUE": "coinbase"}
        self.assertEqual(get_preferred_execution_venue(env), "coinbase")

    def test_multi_venue_markers_do_not_force_single_broker(self):
        for marker in ("", "multi_venue", "multi-venue", "auto", "all"):
            with self.subTest(marker=marker):
                env = {"PRIMARY_EXECUTION_VENUE": marker}
                self.assertIsNone(get_preferred_execution_venue(env))


if __name__ == "__main__":
    unittest.main()
