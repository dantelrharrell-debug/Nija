import os
import unittest
from unittest.mock import patch

from bot.startup_validation import validate_operational_environment_config


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
            self.assertTrue(any("Conflicting mode flags" in msg for _, msg in result.risks))

    def test_invalid_redis_url_fails_closed(self):
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
            self.assertTrue(any("NIJA_REDIS_URL format is invalid" in msg for _, msg in result.risks))

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
            self.assertTrue(any("NIJA_EXECUTION_UNLOCK_TIMEOUT_S is invalid" in msg for _, msg in result.risks))

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
            self.assertFalse(any(risk.value == "environment_misconfiguration" for risk, _ in result.risks))


if __name__ == "__main__":
    unittest.main()
