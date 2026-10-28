"""Offline fail-closed tests for five-source Kraken registry composition."""
import sys
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    package = types.ModuleType("bot")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = package

from bot.kraken_five_source_registry_v487 import (
    REMAINING_FIELDS, compose_five_source_kraken_registry,
)
from bot.kraken_reviewed_registry_composition_v484 import KrakenRegistryIncomplete
from bot.kraken_reviewed_producer_bundle_v483 import FIELDS
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot import pretrade_independent_attestation as att


def no_io():
    raise AssertionError("composition must not query production")


def inputs():
    broker = {field: no_io for field in FIELDS}
    rest = {field: no_io for field in REMAINING_FIELDS}
    ids = {field: "reviewed-" + field for field in REQUIRED}
    return broker, rest, ids


class TestFiveSourceComposition(unittest.TestCase):
    def test_exact_five_plus_eight_no_install(self):
        broker, rest, ids = inputs()
        self.assertEqual(len(FIELDS), 4)
        self.assertEqual(len(REMAINING_FIELDS), 8)
        previous = att._COLLECTOR
        providers, trusted = compose_five_source_kraken_registry(
            broker_providers=broker,
            protective_exit_provider=no_io,
            independent_providers=rest,
            trusted_provider_ids=ids,
            independently_reviewed=True,
        )
        self.assertEqual(set(providers), set(REQUIRED))
        self.assertEqual(set(trusted), set(REQUIRED))
        self.assertIs(att._COLLECTOR, previous)
        with self.assertRaises(TypeError):
            providers["risk_limits"] = no_io

    def test_review_required(self):
        broker, rest, ids = inputs()
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_five_source_kraken_registry(
                broker_providers=broker, protective_exit_provider=no_io,
                independent_providers=rest, trusted_provider_ids=ids,
            )

    def test_missing_or_extra_authority_source_denied(self):
        broker, rest, ids = inputs()
        del rest["writer_lease"]
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_five_source_kraken_registry(
                broker_providers=broker, protective_exit_provider=no_io,
                independent_providers=rest, trusted_provider_ids=ids,
                independently_reviewed=True,
            )

    def test_noncallable_protection_denied(self):
        broker, rest, ids = inputs()
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_five_source_kraken_registry(
                broker_providers=broker, protective_exit_provider=True,
                independent_providers=rest, trusted_provider_ids=ids,
                independently_reviewed=True,
            )

    def test_cross_authority_reuse_denied(self):
        broker, rest, ids = inputs()
        ids["writer_lease"] = ids["account_identity"]
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_five_source_kraken_registry(
                broker_providers=broker, protective_exit_provider=no_io,
                independent_providers=rest, trusted_provider_ids=ids,
                independently_reviewed=True,
            )


if __name__ == "__main__":
    unittest.main()
