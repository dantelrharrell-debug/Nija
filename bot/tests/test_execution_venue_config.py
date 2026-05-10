import unittest

from bot.execution_venue_config import (
    _is_enabled,
    get_preferred_execution_venue,
    should_initialize_coinbase_platform,
)


class ExecutionVenueConfigTests(unittest.TestCase):
    def test_is_enabled_handles_empty_values(self):
        self.assertTrue(_is_enabled(None))
        self.assertTrue(_is_enabled(""))
        self.assertFalse(_is_enabled(None, default=False))
        self.assertFalse(_is_enabled("   ", default=False))

    def test_is_enabled_handles_falsey_strings(self):
        for value in ("0", "false", "False", "no", "off"):
            with self.subTest(value=value):
                self.assertFalse(_is_enabled(value))

    def test_is_enabled_handles_truthy_strings(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(_is_enabled(value, default=False))

    def test_coinbase_platform_allowed_with_kraken_primary(self):
        env = {
            "ENABLE_COINBASE_TRADING": "true",
            "PRIMARY_EXECUTION_VENUE": "kraken",
        }
        self.assertTrue(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_defaults_to_disabled_without_trading_flag(self):
        self.assertFalse(should_initialize_coinbase_platform({}))

    def test_coinbase_platform_blocked_when_trading_disabled(self):
        env = {"ENABLE_COINBASE_TRADING": "false"}
        self.assertFalse(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_blocked_when_exchange_disabled(self):
        env = {"ENABLE_COINBASE": "false", "ENABLE_COINBASE_TRADING": "true"}
        self.assertFalse(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_blocked_when_globally_disabled(self):
        env = {
            "ENABLE_COINBASE": "true",
            "ENABLE_COINBASE_TRADING": "true",
            "NIJA_DISABLE_COINBASE": "true",
        }
        self.assertFalse(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_env_matrix(self):
        cases = (
            ({}, False),
            ({"ENABLE_COINBASE_TRADING": "true"}, True),
            ({"ENABLE_COINBASE": "true", "ENABLE_COINBASE_TRADING": "true"}, True),
            ({"ENABLE_COINBASE": "false", "ENABLE_COINBASE_TRADING": "true"}, False),
            ({"NIJA_DISABLE_COINBASE": "true", "ENABLE_COINBASE_TRADING": "true"}, False),
            (
                {
                    "NIJA_DISABLE_COINBASE": "true",
                    "ENABLE_COINBASE": "true",
                    "ENABLE_COINBASE_TRADING": "true",
                },
                False,
            ),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                self.assertEqual(should_initialize_coinbase_platform(env), expected)

    def test_preferred_execution_venue_forces_single_broker(self):
        for venue in ("coinbase", "kraken", "okx", "binance", "alpaca"):
            with self.subTest(venue=venue):
                env = {"PRIMARY_EXECUTION_VENUE": venue}
                self.assertEqual(get_preferred_execution_venue(env), venue)

    def test_multi_venue_markers_do_not_force_single_broker(self):
        for marker in ("", "multi_venue", "multi-venue", "auto", "all", "best"):
            with self.subTest(marker=marker):
                env = {"PRIMARY_EXECUTION_VENUE": marker}
                self.assertIsNone(get_preferred_execution_venue(env))

    def test_unsupported_execution_venue_does_not_force_single_broker(self):
        self.assertIsNone(get_preferred_execution_venue({"PRIMARY_EXECUTION_VENUE": "unknown"}))
        self.assertIsNone(get_preferred_execution_venue({}))


if __name__ == "__main__":
    unittest.main()
