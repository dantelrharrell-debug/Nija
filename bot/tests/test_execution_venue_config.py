import unittest

from bot.execution_venue_config import (
    _parse_bool_flag,
    get_coinbase_platform_skip_reasons,
    get_okx_platform_skip_reasons,
    get_preferred_execution_venue,
    should_initialize_coinbase_platform,
    should_initialize_okx_platform,
)


class ExecutionVenueConfigTests(unittest.TestCase):
    def test_parse_bool_flag_handles_empty_values(self):
        self.assertTrue(_parse_bool_flag(None))
        self.assertTrue(_parse_bool_flag(""))
        self.assertFalse(_parse_bool_flag(None, default=False))
        self.assertFalse(_parse_bool_flag("   ", default=False))

    def test_parse_bool_flag_handles_falsey_strings(self):
        for value in ("0", "false", "False", "no", "off"):
            with self.subTest(value=value):
                self.assertFalse(_parse_bool_flag(value))

    def test_parse_bool_flag_handles_truthy_strings(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(_parse_bool_flag(value, default=False))

    def test_coinbase_platform_allowed_with_kraken_primary(self):
        env = {
            "ENABLE_COINBASE_TRADING": "true",
            "PRIMARY_EXECUTION_VENUE": "kraken",
        }
        self.assertTrue(should_initialize_coinbase_platform(env))

    def test_coinbase_platform_defaults_to_enabled_without_trading_flag(self):
        self.assertTrue(should_initialize_coinbase_platform({}))

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

    def test_coinbase_platform_skip_reasons(self):
        env = {"ENABLE_COINBASE": "false", "ENABLE_COINBASE_TRADING": "false"}
        self.assertEqual(
            get_coinbase_platform_skip_reasons(env),
            ["ENABLE_COINBASE=false", "ENABLE_COINBASE_TRADING!=true"],
        )

    def test_coinbase_platform_env_matrix(self):
        cases = (
            ({}, True),
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

    def test_okx_platform_allowed_with_credentials_by_default(self):
        self.assertTrue(should_initialize_okx_platform({}, credentials_configured=True))

    def test_okx_platform_blocked_without_credentials(self):
        self.assertFalse(should_initialize_okx_platform({}, credentials_configured=False))
        self.assertEqual(
            get_okx_platform_skip_reasons({}, credentials_configured=False),
            ["credentials not configured"],
        )

    def test_okx_platform_blocked_when_disabled(self):
        env = {"NIJA_DISABLE_OKX": "true"}
        self.assertFalse(should_initialize_okx_platform(env, credentials_configured=True))
        self.assertEqual(
            get_okx_platform_skip_reasons(env, credentials_configured=True),
            ["NIJA_DISABLE_OKX=true"],
        )

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
