"""Offline account-bound balance tests; no broker credentials or network."""
import copy
import hashlib
import json
import sys
import types
import unittest
from pathlib import Path

# Keep offline execution independent of bot/__init__ startup side effects.
if "bot" not in sys.modules:
    package = types.ModuleType("bot")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = package

from bot.kraken_authenticated_balance_provider import KrakenBalanceDenied, make_kraken_balance_provider
from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate

KEY = "synthetic-public-key-identifier"
IBAN = "AA00 TEST TEST TEST"
KEY_PIN = hashlib.sha256(KEY.encode()).hexdigest()
ACCOUNT_PIN = hashlib.sha256(("kraken\0" + IBAN).encode()).hexdigest()
CATEGORY = object()


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None

    def __init__(self):
        self.api = types.SimpleNamespace(key=KEY)
        self.calls = []
        self.action = None
        self.rows = {"ZUSD": {"balance": "100.00000001", "hold_trade": "20"}}
        self.identity = {"apiKey": KEY, "iban": IBAN, "validUntil": "0"}

    def _kraken_private_call(self, method, params, *, category):
        assert params == {} and category is CATEGORY
        assert method in {"GetApiKeyInfo", "BalanceEx"}
        self.calls.append(method)
        if self.action:
            self.action(method)
        return {"error": [], "result": copy.deepcopy(self.rows if method == "BalanceEx" else self.identity)}


class BalanceTests(unittest.TestCase):
    def make(self, broker, *, end=1001.0, account_pin=ACCOUNT_PIN, key_pin=KEY_PIN):
        ticks = iter([1000.0, 1000.1, 1000.2, 1000.3, end])
        return make_kraken_balance_provider(
            broker, account_scope="platform:kraken", approved_iban_sha256=account_pin,
            approved_api_key_sha256=key_pin, reviewed_provider_id="reviewed-balance-provider",
            monitoring_category=CATEGORY, clock=lambda: next(ticks),
        )

    def test_exact_existing_client_only_redacted_single_field(self):
        b = Broker()
        row = self.make(b)()
        self.assertEqual(b.calls, ["GetApiKeyInfo", "BalanceEx", "GetApiKeyInfo"])
        self.assertTrue(row["verified"])
        self.assertFalse(row["authorizes_orders"])
        self.assertEqual(row["observed_at_epoch"], 1000.0)
        for private in [KEY, IBAN, KEY_PIN, ACCOUNT_PIN, "100.00000001", "ZUSD"]:
            self.assertNotIn(private, json.dumps(row))
        ids = {field: "reviewed-" + field for field in REQUIRED}
        ids["broker_balances"] = row["provider_id"]
        certificate = evaluate_pretrade_certificate(
            {"broker_balances": row}, account="platform:kraken",
            trusted_provider_ids=ids, now_epoch=1001.0,
        )
        self.assertNotIn("broker_balances", certificate["missing"])
        self.assertIn("position_ledger_reconciliation", certificate["missing"])
        self.assertFalse(certificate["certified"])
        self.assertFalse(certificate["authorizes_orders"])

    def test_documented_empty_wallet_is_not_ledger_certification(self):
        b = Broker()
        b.rows = {}
        self.assertTrue(self.make(b)()["verified"])

    def test_credit_fields_and_asset_variants_remain_distinct(self):
        b = Broker()
        b.rows = {"USDT": {"balance": "1", "hold_trade": "0"},
                  "USDT.F": {"balance": "2", "hold_trade": "0", "credit": "3", "credit_used": "1"}}
        self.assertTrue(self.make(b)()["verified"])

    def test_missing_or_wrong_account_pin_denies_before_balance_read(self):
        for pin in ["", "a" * 64]:
            b = Broker()
            with self.subTest(pin=pin):
                with self.assertRaises(ValueError):
                    self.make(b, account_pin=pin)()
                self.assertNotIn("BalanceEx", b.calls)

    def test_transport_key_and_gateway_deny_before_io(self):
        for setup in [lambda b: setattr(b.api, "key", "other"),
                      lambda b: setattr(b, "_gateway_url", "https://gateway.invalid")]:
            b = Broker()
            setup(b)
            with self.assertRaises(KrakenBalanceDenied):
                self.make(b)()
            self.assertEqual(b.calls, [])

    def test_account_changes_during_balance_read_deny(self):
        b = Broker()
        # Change the routing role as well; platform user_id alone is not a user scope.
        def switch(method):
            if method == "BalanceEx":
                b.account_type, b.user_id = "user", "other"
        b.action = switch
        with self.assertRaises(KrakenBalanceDenied):
            self.make(b)()

    def test_account_identity_changes_during_balance_read_deny(self):
        b = Broker()
        def switch(method):
            if method == "BalanceEx":
                b.identity["iban"] = "OTHER ACCOUNT"
        b.action = switch
        with self.assertRaises(KrakenBalanceDenied):
            self.make(b)()

    def test_transport_key_changes_during_read_deny(self):
        b = Broker()
        def switch(method):
            if method == "BalanceEx":
                b.api.key = "other"
        b.action = switch
        with self.assertRaises(KrakenBalanceDenied):
            self.make(b)()

    def test_bad_fields_numbers_assets_and_overheld_balances_deny(self):
        invalid = [
            {"ZUSD": {"balance": "1"}},
            {"ZUSD": {"balance": "1", "hold_trade": "0", "credit": "1"}},
            {"ZUSD": {"balance": "1", "hold_trade": "0", "pending_credit": "1"}},
            {"ZUSD": {"balance": "1", "hold_trade": "2"}},
            {"bad asset": {"balance": "1", "hold_trade": "0"}},
        ]
        for value in [True, None, "NaN", "Infinity", "-1", "1e9999", "x"]:
            invalid.append({"ZUSD": {"balance": value, "hold_trade": "0"}})
        for rows in invalid:
            b = Broker()
            b.rows = rows
            with self.subTest(rows=rows), self.assertRaises(KrakenBalanceDenied):
                self.make(b)()

    def test_stale_future_and_boolean_clock_deny(self):
        for end in [1061.0, 999.0, True, float("nan")]:
            with self.subTest(end=end), self.assertRaises(KrakenBalanceDenied):
                self.make(Broker(), end=end)()

    def test_transport_errors_are_redacted(self):
        b = Broker()
        def fail(method):
            if method == "BalanceEx":
                raise RuntimeError("secret credential payload")
        b.action = fail
        with self.assertRaises(KrakenBalanceDenied) as error:
            self.make(b)()
        self.assertNotIn("secret", str(error.exception))
        self.assertIsNone(error.exception.__cause__)

    def test_uppercase_reviewed_fingerprints_match_existing_identity_contract(self):
        self.assertTrue(self.make(Broker(), account_pin=ACCOUNT_PIN.upper(), key_pin=KEY_PIN.upper())()["verified"])

    def test_missing_disconnected_client_denies(self):
        b = Broker()
        b.connected = False
        with self.assertRaises(KrakenBalanceDenied):
            self.make(b)()
        self.assertEqual(b.calls, [])

    def test_bad_envelopes_cannot_certify_balances(self):
        for envelope in [None, {"result": {}}, {"error": ["denied"], "result": {}},
                         {"error": [], "result": [], "next": "unconsumed-page"}]:
            b = Broker()
            original = b._kraken_private_call
            def read(method, params, *, category):
                return envelope if method == "BalanceEx" else original(method, params, category=category)
            b._kraken_private_call = read
            with self.subTest(envelope=envelope), self.assertRaises(KrakenBalanceDenied):
                self.make(b)()

    def test_changed_balance_changes_evidence_id(self):
        b = Broker()
        first = self.make(b)()["evidence_id"]
        b.rows["ZUSD"]["balance"] = "101.00000001"
        self.assertNotEqual(first, self.make(b)()["evidence_id"])


if __name__ == "__main__":
    unittest.main()
