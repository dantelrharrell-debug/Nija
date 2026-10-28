"""Offline fail-closed checks for the v487 Kraken composition adapter."""
import unittest
from unittest.mock import patch

from bot.kraken_reviewed_five_field_bundle_v487 import (
    FIELDS, MISSING_FIELDS, make_reviewed_kraken_five_field_bundle,
)
from bot.kraken_reviewed_producer_bundle_v483 import KrakenCompositionDenied
from bot.pretrade_attestation_validation_v452 import REQUIRED


class FakeBroker:
    def _kraken_private_call(self, *args, **kwargs):
        raise AssertionError("constructor must never contact broker")


class TestReviewedFiveFieldBundle(unittest.TestCase):
    def setUp(self):
        self.params = dict(
            broker=FakeBroker(),
            account_scope="platform:kraken",
            approved_api_key_sha256="a" * 64,
            approved_iban_sha256="b" * 64,
            reviewed_provider_ids={field: "reviewed_" + field for field in FIELDS},
            reviewed_ledger_provider_id="independent_ledger_provider",
            independent_open_intents=lambda: {},
            independent_positions=lambda: {},
            monitoring_category="read_only",
            independently_reviewed=True,
        )

    def test_five_of_thirteen_non_authorizing(self):
        self.assertEqual(len(FIELDS), 5)
        self.assertEqual(len(MISSING_FIELDS), 8)
        self.assertEqual(set(FIELDS) | set(MISSING_FIELDS), set(REQUIRED))
        with patch("bot.kraken_reviewed_five_field_bundle_v487.make_reviewed_kraken_producer_bundle") as base, patch(
            "bot.kraken_reviewed_five_field_bundle_v487.make_kraken_protective_exit_provider"
        ) as exit_provider:
            base.return_value = {field: (lambda: {}) for field in FIELDS[:-1]}
            exit_provider.return_value = lambda: {}
            bundle = make_reviewed_kraken_five_field_bundle(**self.params)
        self.assertEqual(set(bundle), set(FIELDS))
        with self.assertRaises(TypeError):
            bundle["other"] = lambda: {}
        self.assertEqual(base.call_args.kwargs["independently_reviewed"], True)

    def test_denies_unreviewed_and_duplicate_ids(self):
        for mutation in (
            {"independently_reviewed": False},
            {"reviewed_provider_ids": {**self.params["reviewed_provider_ids"], "protective_exit_readback": "reviewed_account_identity"}},
            {"reviewed_provider_ids": {field: "reviewed_" + field for field in FIELDS[:-1]}},
            {"independent_positions": None},
            {"account_scope": "user:somebody:kraken"},
            {"approved_api_key_sha256": "invalid"},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(KrakenCompositionDenied):
                    make_reviewed_kraken_five_field_bundle(**{**self.params, **mutation})

    def test_no_broker_io_at_construction(self):
        bundle = make_reviewed_kraken_five_field_bundle(**self.params)
        self.assertEqual(set(bundle), set(FIELDS))


if __name__ == "__main__":
    unittest.main()
