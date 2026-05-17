"""
Tests for the Kraken Error Taxonomy Layer.

Covers:
- classify_kraken_error() pattern matching
- Correct policy mapping for AUTH, NONCE, RATE_LIMIT, PERMISSION categories
- Convenience helpers: is_fatal_auth_error, is_nonce_error, is_rate_limit_error,
  is_permission_error
- ExecutionResult.retry_policy field population
- Fallback to UNKNOWN for unrecognised strings
"""

import sys
import os
import unittest

# Ensure the bot package is importable from the test runner's working directory.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from bot.kraken_error_taxonomy import (
    classify_kraken_error,
    get_retry_policy,
    is_fatal_auth_error,
    is_nonce_error,
    is_rate_limit_error,
    is_permission_error,
    KrakenErrorCategory,
    KrakenRetryPolicy,
    KrakenErrorTaxonomy,
)
from bot.execution_result import ExecutionResult, OrderStatus


class TestKrakenErrorCategoryMapping(unittest.TestCase):
    """Each Kraken error category maps to the correct retry policy."""

    def _assert_policy(self, error_text: str, expected_policy: KrakenRetryPolicy) -> None:
        t = classify_kraken_error(error_text)
        self.assertEqual(
            t.policy,
            expected_policy,
            f"Expected {expected_policy} for {error_text!r}, got {t.policy}",
        )

    # ── AUTH → STOP ────────────────────────────────────────────────────────

    def test_auth_invalid_key_stops(self):
        self._assert_policy("EAuth:Invalid key", KrakenRetryPolicy.STOP)

    def test_auth_invalid_signature_stops(self):
        self._assert_policy("EAuth:Invalid signature", KrakenRetryPolicy.STOP)

    def test_auth_locked_stops(self):
        self._assert_policy("EAuth:Locked", KrakenRetryPolicy.STOP)

    def test_auth_failed_generic_stops(self):
        self._assert_policy("EAuth:Failed", KrakenRetryPolicy.STOP)

    def test_auth_case_insensitive(self):
        self._assert_policy("EAUTH:INVALID KEY", KrakenRetryPolicy.STOP)

    # ── NONCE → RETRY ─────────────────────────────────────────────────────

    def test_nonce_invalid_retries(self):
        self._assert_policy("EAPI:Invalid nonce", KrakenRetryPolicy.RETRY)

    def test_nonce_window_retries(self):
        self._assert_policy("nonce out of window", KrakenRetryPolicy.RETRY)

    def test_nonce_invalid_mixed_case(self):
        self._assert_policy("eapi:invalid nonce", KrakenRetryPolicy.RETRY)

    # ── RATE_LIMIT → BACKOFF ──────────────────────────────────────────────

    def test_api_rate_limit_backoff(self):
        self._assert_policy("EAPI:Rate limit exceeded", KrakenRetryPolicy.BACKOFF)

    def test_order_rate_limit_backoff(self):
        self._assert_policy("EOrder:Rate limit exceeded", KrakenRetryPolicy.BACKOFF)

    def test_rate_limit_mixed_case(self):
        self._assert_policy("eapi:rate limit exceeded", KrakenRetryPolicy.BACKOFF)

    def test_429_response_backoff(self):
        self._assert_policy("HTTP 429 too many requests", KrakenRetryPolicy.BACKOFF)

    # ── PERMISSION → CONFIG_FAIL ──────────────────────────────────────────

    def test_permission_denied_config_fail(self):
        self._assert_policy("EGeneral:Permission denied", KrakenRetryPolicy.CONFIG_FAIL)

    def test_eapi_invalid_permission_config_fail(self):
        self._assert_policy("EAPI:Invalid permission", KrakenRetryPolicy.CONFIG_FAIL)

    def test_insufficient_permission_config_fail(self):
        self._assert_policy("insufficient permission for this request", KrakenRetryPolicy.CONFIG_FAIL)

    def test_feature_disabled_config_fail(self):
        self._assert_policy("EAPI:Feature disabled", KrakenRetryPolicy.CONFIG_FAIL)


class TestKrakenErrorCategories(unittest.TestCase):
    """Correct categories are assigned."""

    def test_auth_category(self):
        t = classify_kraken_error("EAuth:Invalid key")
        self.assertEqual(t.category, KrakenErrorCategory.AUTH)

    def test_nonce_category(self):
        t = classify_kraken_error("EAPI:Invalid nonce")
        self.assertEqual(t.category, KrakenErrorCategory.NONCE)

    def test_rate_limit_category(self):
        t = classify_kraken_error("EAPI:Rate limit exceeded")
        self.assertEqual(t.category, KrakenErrorCategory.RATE_LIMIT)

    def test_permission_category(self):
        t = classify_kraken_error("EGeneral:Permission denied")
        self.assertEqual(t.category, KrakenErrorCategory.PERMISSION)

    def test_funds_category(self):
        t = classify_kraken_error("EOrder:Insufficient funds")
        self.assertEqual(t.category, KrakenErrorCategory.FUNDS)

    def test_order_minimum_category(self):
        t = classify_kraken_error("EOrder:Order minimum not met")
        self.assertEqual(t.category, KrakenErrorCategory.ORDER)

    def test_service_unavailable_category(self):
        t = classify_kraken_error("EService:Unavailable")
        self.assertEqual(t.category, KrakenErrorCategory.SERVICE)

    def test_network_timeout_category(self):
        t = classify_kraken_error("connection timeout")
        self.assertEqual(t.category, KrakenErrorCategory.NETWORK)

    def test_unknown_category_fallback(self):
        t = classify_kraken_error("some completely unrecognised message xyz")
        self.assertEqual(t.category, KrakenErrorCategory.UNKNOWN)


class TestRetryDelayAndMaxRetries(unittest.TestCase):
    """Retry delay / max retry counts reflect error severity."""

    def test_auth_zero_retries(self):
        t = classify_kraken_error("EAuth:Invalid key")
        self.assertEqual(t.max_retries, 0)
        self.assertEqual(t.retry_delay_s, 0.0)

    def test_nonce_positive_delay(self):
        t = classify_kraken_error("EAPI:Invalid nonce")
        self.assertGreater(t.retry_delay_s, 0)
        self.assertGreater(t.max_retries, 0)

    def test_rate_limit_longer_delay(self):
        t = classify_kraken_error("EAPI:Rate limit exceeded")
        self.assertGreaterEqual(t.retry_delay_s, 5.0)

    def test_permission_zero_retries(self):
        t = classify_kraken_error("EGeneral:Permission denied")
        self.assertEqual(t.max_retries, 0)


class TestConvenienceHelpers(unittest.TestCase):
    """Boolean helper functions."""

    def test_is_fatal_auth_error_true(self):
        self.assertTrue(is_fatal_auth_error("EAuth:Invalid key"))

    def test_is_fatal_auth_error_false_on_nonce(self):
        self.assertFalse(is_fatal_auth_error("EAPI:Invalid nonce"))

    def test_is_nonce_error_true(self):
        self.assertTrue(is_nonce_error("EAPI:Invalid nonce"))

    def test_is_nonce_error_false_on_auth(self):
        self.assertFalse(is_nonce_error("EAuth:Invalid key"))

    def test_is_rate_limit_error_true(self):
        self.assertTrue(is_rate_limit_error("EAPI:Rate limit exceeded"))

    def test_is_permission_error_true(self):
        self.assertTrue(is_permission_error("EGeneral:Permission denied"))

    def test_get_retry_policy_returns_correct_enum(self):
        self.assertIs(get_retry_policy("EAPI:Invalid nonce"), KrakenRetryPolicy.RETRY)

    def test_empty_string_returns_unknown(self):
        t = classify_kraken_error("")
        self.assertEqual(t.category, KrakenErrorCategory.UNKNOWN)

    def test_whitespace_only_returns_unknown(self):
        t = classify_kraken_error("   ")
        self.assertEqual(t.category, KrakenErrorCategory.UNKNOWN)


class TestExecutionResultRetryPolicy(unittest.TestCase):
    """ExecutionResult.retry_policy is populated correctly."""

    def test_retry_policy_field_defaults_none(self):
        result = ExecutionResult(
            status=OrderStatus.ACCEPTED,
            symbol="BTC/USD",
            side="buy",
        )
        self.assertIsNone(result.retry_policy)

    def test_retry_policy_stop_on_auth_failure(self):
        taxonomy = classify_kraken_error("EAuth:Invalid key")
        result = ExecutionResult(
            status=OrderStatus.FAILED,
            symbol="ETH/USD",
            side="sell",
            error_code=taxonomy.canonical_code,
            retry_policy=taxonomy.policy,
        )
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.STOP)

    def test_retry_policy_retry_on_nonce(self):
        taxonomy = classify_kraken_error("EAPI:Invalid nonce")
        result = ExecutionResult(
            status=OrderStatus.REJECTED,
            symbol="SOL/USD",
            side="buy",
            error_code=taxonomy.canonical_code,
            retry_policy=taxonomy.policy,
        )
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.RETRY)

    def test_retry_policy_backoff_on_rate_limit(self):
        taxonomy = classify_kraken_error("EAPI:Rate limit exceeded")
        result = ExecutionResult(
            status=OrderStatus.REJECTED,
            symbol="ADA/USD",
            side="sell",
            error_code=taxonomy.canonical_code,
            retry_policy=taxonomy.policy,
        )
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.BACKOFF)

    def test_retry_policy_config_fail_on_permission(self):
        taxonomy = classify_kraken_error("EGeneral:Permission denied")
        result = ExecutionResult(
            status=OrderStatus.FAILED,
            symbol="DOT/USD",
            side="buy",
            error_code=taxonomy.canonical_code,
            retry_policy=taxonomy.policy,
        )
        self.assertEqual(result.retry_policy, KrakenRetryPolicy.CONFIG_FAIL)


class TestReturnTypeContract(unittest.TestCase):
    """classify_kraken_error always returns a KrakenErrorTaxonomy."""

    def test_always_returns_taxonomy(self):
        for text in [
            "EAuth:Invalid key",
            "EAPI:Invalid nonce",
            "EAPI:Rate limit exceeded",
            "EGeneral:Permission denied",
            "EOrder:Insufficient funds",
            "EService:Unavailable",
            "connection timeout",
            "an unrecognised error",
            "",
        ]:
            with self.subTest(text=text):
                t = classify_kraken_error(text)
                self.assertIsInstance(t, KrakenErrorTaxonomy)
                self.assertIsInstance(t.category, KrakenErrorCategory)
                self.assertIsInstance(t.policy, KrakenRetryPolicy)
                self.assertIsInstance(t.canonical_code, str)
                self.assertTrue(t.canonical_code)


if __name__ == "__main__":
    unittest.main()
