import os
import unittest
from unittest.mock import patch

from bot.startup_validation import (
    StartupRisk,
    StartupValidationResult,
    display_validation_results,
    validate_account_hierarchy,
    validate_operational_environment_config,
)


class TestStartupValidationEnvMisconfiguration(unittest.TestCase):
    def test_conflicting_mode_flags_fail_closed(self):
        with patch.dict(
            os.environ,
            {
                "DRY_RUN_MODE": "true",
                "PAPER_MODE": "false",
                "LIVE_CAPITAL_VERIFIED": "true",
                "LIVE_TRADING": "false",
                "NIJA_REDIS_URL": "redis://localhost:6379/0",
                "NIJA_EXECUTION_UNLOCK_TIMEOUT_S": "15",
            },
            clear=True,
        ):
            result = validate_operational_environment_config()
            self.assertTrue(result.critical_failure)
            self.assertTrue(any(risk == StartupRisk.ENVIRONMENT_MISCONFIGURATION for risk, _ in result.risks))

    def test_invalid_redis_url_scheme_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "DRY_RUN_MODE": "false",
                "PAPER_MODE": "false",
                "LIVE_CAPITAL_VERIFIED": "true",
                "LIVE_TRADING": "false",
                "NIJA_REDIS_URL": "https://example.com/not-redis",
                "NIJA_EXECUTION_UNLOCK_TIMEOUT_S": "15",
            },
            clear=True,
        ):
            result = validate_operational_environment_config()
            self.assertTrue(result.critical_failure)
            self.assertTrue(any(risk == StartupRisk.ENVIRONMENT_MISCONFIGURATION for risk, _ in result.risks))

    def test_invalid_execution_unlock_timeout_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "DRY_RUN_MODE": "false",
                "PAPER_MODE": "false",
                "LIVE_CAPITAL_VERIFIED": "false",
                "LIVE_TRADING": "false",
                "NIJA_REDIS_URL": "redis://localhost:6379/0",
                "NIJA_EXECUTION_UNLOCK_TIMEOUT_S": "0",
            },
            clear=True,
        ):
            result = validate_operational_environment_config()
            self.assertTrue(result.critical_failure)
            self.assertTrue(any(risk == StartupRisk.ENVIRONMENT_MISCONFIGURATION for risk, _ in result.risks))

    def test_valid_configuration_passes(self):
        with patch.dict(
            os.environ,
            {
                "DRY_RUN_MODE": "true",
                "PAPER_MODE": "false",
                "LIVE_CAPITAL_VERIFIED": "false",
                "LIVE_TRADING": "false",
                "NIJA_REDIS_URL": "redis://localhost:6379/0",
                "NIJA_EXECUTION_UNLOCK_TIMEOUT_S": "30",
            },
            clear=True,
        ):
            result = validate_operational_environment_config()
            self.assertFalse(result.critical_failure)
            self.assertFalse(any(risk == StartupRisk.ENVIRONMENT_MISCONFIGURATION for risk, _ in result.risks))


    def test_enabled_kraken_user_missing_secret_is_reported(self):
        with patch.dict(
            os.environ,
            {
                "KRAKEN_PLATFORM_API_KEY": "platform_key_12345",
                "KRAKEN_PLATFORM_API_SECRET": "p" * 40,
                "KRAKEN_USER_DAIVON_API_KEY": "daivon_key_12345",
            },
            clear=True,
        ):
            result = validate_account_hierarchy()

        self.assertTrue(
            any("enabled user daivon_frazier" in warning and "KRAKEN_USER_DAIVON_API_SECRET" in warning
                for warning in result.warnings),
            result.warnings,
        )

    def test_enabled_kraken_users_with_key_secret_pairs_are_counted_viable(self):
        with patch.dict(
            os.environ,
            {
                "KRAKEN_PLATFORM_API_KEY": "platform_key_12345",
                "KRAKEN_PLATFORM_API_SECRET": "p" * 40,
                "KRAKEN_USER_DAIVON_API_KEY": "daivon_key_12345",
                "KRAKEN_USER_DAIVON_API_SECRET": "d" * 40,
                "KRAKEN_USER_TANIA_API_KEY": "tania_key_12345",
                "KRAKEN_USER_TANIA_API_SECRET": "t" * 40,
            },
            clear=True,
        ):
            result = validate_account_hierarchy()

        self.assertFalse(result.warnings, result.warnings)
        self.assertTrue(
            any("2 enabled Kraken user account(s) have viable credentials" in info for info in result.info),
            result.info,
        )

    def test_display_validation_results_labels_log_monitoring_as_informational(self):
        with self.assertLogs("nija", level="INFO") as captured:
            display_validation_results(StartupValidationResult())
        self.assertTrue(
            any("LOG MONITORING (informational)" in line for line in captured.output),
            "Expected startup validation output to label log monitoring guidance as informational.",
        )


if __name__ == "__main__":
    unittest.main()
