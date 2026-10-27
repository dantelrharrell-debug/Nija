"""Offline real-dependency integration for v482 and the existing v480 identity verifier.

No external network or exchange credentials. An already-authenticated broker is
simulated, and only the specified read-only GetApiKeyInfo/OpenOrders calls exist.
"""
import copy
import hashlib
import json
import sys
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = pkg

from bot.kraken_authenticated_open_order_reconciliation_v482 import (  # noqa: E402
    KrakenOpenOrderDenied, make_kraken_open_order_reconciliation_provider,
)
from bot.pretrade_attestation_validation_v452 import (  # noqa: E402
    REQUIRED, evaluate_pretrade_certificate,
)

KEY = "synthetic-public-key-identifier"
IBAN = "AA00 TEST TEST TEST"
KEY_SHA = hashlib.sha256(KEY.encode()).hexdigest()
IBAN_SHA = hashlib.sha256(("kraken\0" + IBAN).encode()).hexdigest()
SCOPE = "platform:kraken"
CATEGORY = object()
OID = "OABCDE-ABCDE-ABCDEF"


class AuthenticatedBroker:
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    connected = True

    def __init__(self):
        self.calls = []
        self.public_key = KEY
        self.iiban = IBAN
        self.open = {OID: {
            "status": "open",
            "descr": {"pair": "XETHZUSD", "type": "sell", "ordertype": "stop-loss", "price": "123"},
            "vol": "0.02", "vol_exec": "0",
        }}

    def _kraken_private_call(self, endpoint, params, *, category):
        if category is not CATEGORY:
            raise AssertionError("unexpected monitoring category")
        self.calls.append((endpoint, copy.deepcopy(params)))
        if endpoint == "GetApiKeyInfo":
            if params:
                raise AssertionError("identity query must be unfiltered")
            return {"error": [], "result": {
                "apiKey": self.public_key, "iban": self.iiban, "validUntil": "0",
            }}
        if endpoint == "OpenOrders":
            if params != {"with_cursor": True, "limit": 50, "trades": True}:
                raise AssertionError("unexpected OpenOrders selector")
            return {"error": [], "result": {"open": copy.deepcopy(self.open), "cursor": {}}}
        raise AssertionError("writes and unreviewed reads must not occur")


class LedgerReader:
    def __init__(self):
        self.open = {OID: {
            "pair": "ETHUSD", "side": "sell", "ordertype": "stop-loss",
            "price": "123.0", "volume": "0.020", "executed": "0.00",
        }}
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"account": SCOPE, "source": "independent_ledger",
                "provider_id": "reviewed-ledger", "snapshot_id": "reviewed-snapshot",
                "snapshot_complete": True, "outstanding_intents_reconciled": True,
                "unresolved_submission_count": 0, "observed_at_epoch": 1000.0,
                "orders": copy.deepcopy(self.open)}


class TestRealIdentityComposition(unittest.TestCase):
    def build(self, broker, ledger, **updates):
        values = dict(
            broker=broker, account_scope=SCOPE, approved_iban_sha256=IBAN_SHA,
            approved_api_key_sha256=KEY_SHA, reviewed_provider_id="reviewed-kraken",
            reviewed_ledger_provider_id="reviewed-ledger",
            independent_open_intents=ledger, monitoring_category=CATEGORY,
            clock=lambda: 1001.0,
        )
        values.update(updates)
        return make_kraken_open_order_reconciliation_provider(**values)

    def test_real_v480_identity_both_sides_and_v452_non_authorization(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        observed = self.build(broker, ledger)()
        self.assertEqual(
            [x[0] for x in broker.calls],
            ["GetApiKeyInfo", "OpenOrders", "OpenOrders", "GetApiKeyInfo"],
        )
        self.assertEqual(ledger.calls, 2)
        self.assertTrue(observed["verified"])
        self.assertFalse(observed["authorizes_orders"])
        trusted = {field: "reviewed-" + field for field in REQUIRED}
        trusted["open_order_reconciliation"] = "reviewed-kraken"
        result = evaluate_pretrade_certificate(
            {"open_order_reconciliation": observed}, account=SCOPE,
            trusted_provider_ids=trusted, now_epoch=1001.0,
        )
        self.assertNotIn("open_order_reconciliation", result["missing"])
        self.assertIn("position_ledger_reconciliation", result["missing"])
        self.assertFalse(result["certified"])
        self.assertFalse(result["authorizes_orders"])
        for sensitive in (KEY, IBAN, OID, KEY_SHA, IBAN_SHA):
            self.assertNotIn(sensitive, json.dumps(observed))

    def test_wrong_external_key_pin_denies_before_open_orders(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger, approved_api_key_sha256="a" * 64)()
        self.assertEqual([x[0] for x in broker.calls], ["GetApiKeyInfo"])
        self.assertEqual(ledger.calls, 0)

    def test_wrong_external_account_pin_denies_before_open_orders(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger, approved_iban_sha256="b" * 64)()
        self.assertEqual([x[0] for x in broker.calls], ["GetApiKeyInfo"])
        self.assertEqual(ledger.calls, 0)

    def test_exact_account_routing_change_denies(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        broker.account_type = "user"
        broker.user_id = "another"
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger)()
        self.assertEqual(broker.calls, [])

    def test_broker_row_and_ledger_disagreement_denies(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        ledger.open[OID]["volume"] = "0.03"
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger)()
        self.assertEqual(ledger.calls, 2)

    def test_real_identity_read_is_required_twice(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        original = broker._kraken_private_call
        def changing(endpoint, params, *, category):
            if endpoint == "GetApiKeyInfo" and len(broker.calls) > 0:
                broker.iiban = "DIFFERENT BROKER"
            return original(endpoint, params, category=category)
        broker._kraken_private_call = changing
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger)()
        self.assertEqual([x[0] for x in broker.calls][-1], "GetApiKeyInfo")

    def test_fails_closed_when_no_pagination_receipt(self):
        broker, ledger = AuthenticatedBroker(), LedgerReader()
        original = broker._kraken_private_call
        def uncursored(endpoint, params, *, category):
            row = original(endpoint, params, category=category)
            if endpoint == "OpenOrders":
                del row["result"]["cursor"]
            return row
        broker._kraken_private_call = uncursored
        with self.assertRaises(KrakenOpenOrderDenied):
            self.build(broker, ledger)()

if __name__ == "__main__":
    unittest.main()
