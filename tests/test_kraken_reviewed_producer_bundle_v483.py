"""Offline regression for partial v483 Kraken provider composition."""
import hashlib
import sys
import types
import unittest
from pathlib import Path
if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = pkg
from bot.kraken_reviewed_producer_bundle_v483 import (
    FIELDS, MISSING_FIELDS, KrakenCompositionDenied,
    make_reviewed_kraken_producer_bundle,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot import pretrade_independent_attestation as att

KEY = hashlib.sha256(b"synthetic key").hexdigest()
IBAN = hashlib.sha256(b"synthetic IIBAN").hexdigest()
CATEGORY = object()
IDS = {key: "reviewed-" + key for key in FIELDS}

class Broker:
    connected = False
    def _kraken_private_call(self, *args, **kwargs):
        raise AssertionError("construction must not perform broker I/O or trade")

def build(**overrides):
    options = dict(
        broker=Broker(), account_scope="platform:kraken",
        approved_api_key_sha256=KEY, approved_iban_sha256=IBAN,
        reviewed_provider_ids=dict(IDS),
        reviewed_ledger_provider_id="independent-ledger-source",
        independent_open_intents=lambda: {},
        monitoring_category=CATEGORY, independently_reviewed=True,
    )
    options.update(overrides)
    return make_reviewed_kraken_producer_bundle(**options)

class TestComposition(unittest.TestCase):
    def test_bundle_partial_immutable_never_installs(self):
        before = att._COLLECTOR
        providers = build()
        self.assertEqual(set(providers), set(FIELDS))
        self.assertEqual(len(MISSING_FIELDS), len(REQUIRED) - 4)
        self.assertTrue(all(callable(p) for p in providers.values()))
        self.assertIs(att._COLLECTOR, before)
        with self.assertRaises(TypeError):
            providers["position_ledger_reconciliation"] = lambda: {}
        with self.assertRaises(Exception):
            providers["broker_balances"]()
        self.assertIs(att._COLLECTOR, before)
    def test_requires_review(self):
        with self.assertRaises(KrakenCompositionDenied):
            build(independently_reviewed=False)
    def test_exact_scope_only(self):
        for scope in ("user:test:kraken", "platform:coinbase", "platform:kraken "):
            with self.subTest(scope=scope), self.assertRaises(KrakenCompositionDenied):
                build(account_scope=scope)
    def test_all_four_pins_and_ids_required(self):
        for kwargs in (
            {"approved_api_key_sha256":""},
            {"approved_iban_sha256":"a"*63},
            {"reviewed_provider_ids":{"account_identity":"id"}},
            {"reviewed_provider_ids":dict.fromkeys(FIELDS,"")},
            {"reviewed_ledger_provider_id": IDS["account_identity"]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(KrakenCompositionDenied):
                build(**kwargs)
    def test_no_separate_nonce_owner(self):
        with self.assertRaises(KrakenCompositionDenied):
            build(broker=object())
    def test_missing_independent_ledger_denied(self):
        with self.assertRaises(KrakenCompositionDenied):
            build(independent_open_intents=None)
    def test_no_unreviewed_clock_or_category(self):
        with self.assertRaises(KrakenCompositionDenied):
            build(clock=3)
        with self.assertRaises(KrakenCompositionDenied):
            build(monitoring_category=None)
if __name__ == "__main__":
    unittest.main()
