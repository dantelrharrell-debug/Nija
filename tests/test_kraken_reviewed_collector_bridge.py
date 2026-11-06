"""Offline denial tests for reviewed collector source composition."""
import unittest
from unittest.mock import patch

from bot.kraken_reviewed_collector_bridge import (
    ReviewedCollectorCompositionDenied,
    compose_authenticated_kraken_collector_sources,
)
from bot.kraken_six_source_binding_contract_v490 import EXPECTED_OWNERS
from bot.pretrade_attestation_validation_v452 import REQUIRED


class FakeBroker:
    def _kraken_private_call(self, *args, **kwargs):
        raise AssertionError("broker I/O must not occur")


class ReviewedCollectorBridgeTests(unittest.TestCase):
    def setUp(self):
        self.sources = {field: (lambda field=field: {}) for field in EXPECTED_OWNERS}
        self.args = dict(
            broker=FakeBroker(),
            approved_api_key_sha256="a" * 64,
            approved_iban_sha256="b" * 64,
            reviewed_provider_ids={field: "id-" + field for field in REQUIRED},
            independent_open_intents=lambda: {},
            independent_positions=lambda: {},
            independent_remaining=self.sources,
            reviewed_source_owners=dict(EXPECTED_OWNERS),
            monitoring_category=object(),
            independently_reviewed=True,
        )

    def test_review_required(self):
        self.args["independently_reviewed"] = False
        with self.assertRaises(ReviewedCollectorCompositionDenied):
            compose_authenticated_kraken_collector_sources(**self.args)

    def test_invalid_identity_pin_denied(self):
        self.args["approved_api_key_sha256"] = "invalid"
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ):
            with self.assertRaisesRegex(
                ReviewedCollectorCompositionDenied,
                "approved_identity_pins_required",
            ):
                compose_authenticated_kraken_collector_sources(**self.args)

    def test_incomplete_source_denied(self):
        self.args["independent_remaining"] = {}
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ):
            with self.assertRaisesRegex(PermissionError, "six_sources_required"):
                compose_authenticated_kraken_collector_sources(**self.args)

    def test_duck_typed_broker_is_denied(self):
        with self.assertRaisesRegex(ReviewedCollectorCompositionDenied, "canonical_broker_required"):
            compose_authenticated_kraken_collector_sources(**self.args)

    def test_composes_without_installing(self):
        providers = {field: (lambda field=field: {}) for field in REQUIRED}
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ), patch(
            "bot.kraken_reviewed_collector_bridge.compose_reviewed_kraken_providers",
            return_value=providers,
        ) as compose:
            actual = compose_authenticated_kraken_collector_sources(**self.args)
        self.assertEqual(set(actual), set(REQUIRED))
        compose.assert_called_once()

    def test_factory_result_with_duplicate_sources_denied(self):
        same_source = lambda: {}
        providers = {field: same_source for field in REQUIRED}
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ), patch(
            "bot.kraken_reviewed_collector_bridge.compose_reviewed_kraken_providers",
            return_value=providers,
        ):
            with self.assertRaisesRegex(ReviewedCollectorCompositionDenied, "incomplete_authenticated_sources"):
                compose_authenticated_kraken_collector_sources(**self.args)

    def test_factory_result_with_noncallable_source_denied(self):
        providers = {field: (lambda field=field: {}) for field in REQUIRED}
        providers[next(iter(REQUIRED))] = None
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ), patch(
            "bot.kraken_reviewed_collector_bridge.compose_reviewed_kraken_providers",
            return_value=providers,
        ):
            with self.assertRaisesRegex(ReviewedCollectorCompositionDenied, "incomplete_authenticated_sources"):
                compose_authenticated_kraken_collector_sources(**self.args)

    def test_incomplete_factory_result_denied(self):
        with patch("bot.broker_manager.KrakenBroker", FakeBroker), patch(
            "bot.kraken_authenticated_account_identity_v478._broker_account_scope",
            return_value="platform:kraken",
        ), patch(
            "bot.kraken_reviewed_collector_bridge.compose_reviewed_kraken_providers",
            return_value={},
        ):
            with self.assertRaises(ReviewedCollectorCompositionDenied):
                compose_authenticated_kraken_collector_sources(**self.args)


if __name__ == "__main__":
    unittest.main()
