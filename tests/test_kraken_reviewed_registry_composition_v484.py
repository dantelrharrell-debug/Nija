"""Offline, no-broker-I/O regression for reviewed Kraken registry composition."""
import unittest
import sys
import types
from pathlib import Path

if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = pkg

from bot.kraken_reviewed_registry_composition_v484 import (
    KrakenRegistryIncomplete, compose_reviewed_kraken_registry,
)
from bot.kraken_reviewed_producer_bundle_v483 import FIELDS
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES
from bot import pretrade_independent_attestation as att


def fake_provider():
    raise AssertionError("composition must not invoke evidence providers")


def fixture():
    broker = {field: fake_provider for field in FIELDS}
    remaining = set(REQUIRED) - set(FIELDS)
    independent = {field: fake_provider for field in remaining}
    ids = {field: "reviewed-" + field for field in REQUIRED}
    return broker, independent, ids


class TestReviewedRegistry(unittest.TestCase):
    def test_complete_registry_is_immutable_and_does_not_install(self):
        broker, independent, ids = fixture()
        before = att._COLLECTOR
        providers, trusted = compose_reviewed_kraken_registry(
            broker_providers=broker, independent_providers=independent,
            trusted_provider_ids=ids, independently_reviewed=True,
        )
        self.assertEqual(set(providers), set(REQUIRED))
        self.assertEqual(set(trusted), set(REQUIRED))
        self.assertIs(att._COLLECTOR, before)
        with self.assertRaises(TypeError):
            providers["risk_limits"] = fake_provider

    def test_review_required(self):
        broker, independent, ids = fixture()
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_reviewed_kraken_registry(
                broker_providers=broker, independent_providers=independent,
                trusted_provider_ids=ids,
            )

    def test_missing_provider_denied(self):
        broker, independent, ids = fixture()
        del independent["protective_exit_readback"]
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_reviewed_kraken_registry(
                broker_providers=broker, independent_providers=independent,
                trusted_provider_ids=ids, independently_reviewed=True,
            )

    def test_noncallable_provider_denied(self):
        broker, independent, ids = fixture()
        independent["operator_authorization"] = True
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_reviewed_kraken_registry(
                broker_providers=broker, independent_providers=independent,
                trusted_provider_ids=ids, independently_reviewed=True,
            )

    def test_cross_authority_id_reuse_denied(self):
        broker, independent, ids = fixture()
        self.assertNotEqual(SOURCES["account_identity"], SOURCES["writer_lease"])
        ids["writer_lease"] = ids["account_identity"]
        with self.assertRaises(KrakenRegistryIncomplete):
            compose_reviewed_kraken_registry(
                broker_providers=broker, independent_providers=independent,
                trusted_provider_ids=ids, independently_reviewed=True,
            )


if __name__ == "__main__":
    unittest.main()
