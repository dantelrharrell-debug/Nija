"""Offline integration: real v477/v480/BalanceEx/v482 providers through v483.

These fixtures never use credentials, network, external state, or runtime hooks.
"""
import copy
import hashlib
import json
import sys
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    package = types.ModuleType("bot")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = package

from bot.kraken_reviewed_producer_bundle_v483 import (  # noqa: E402
    FIELDS, MISSING_FIELDS, make_reviewed_kraken_producer_bundle,
)
from bot.pretrade_attestation_validation_v452 import (  # noqa: E402
    REQUIRED, evaluate_pretrade_certificate,
)
from bot.pretrade_independent_attestation import inspect_authenticated_attestations  # noqa: E402

KEY = "synthetic-transport-api-key-identity"
IBAN = "AA00 REVIEWED SYNTHETIC WALLET"
PIN_KEY = hashlib.sha256(KEY.encode("utf-8")).hexdigest()
PIN_ACCOUNT = hashlib.sha256(("kraken\0" + IBAN).encode("utf-8")).hexdigest()
OID = "OABCDE-ABCDE-ABCDEF"
CATEGORY = object()
IDS = {k: "reviewed-" + k for k in FIELDS}


class Client:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    _gateway_url = ""
    _gateway_only_mode = False

    def __init__(self):
        self.api = types.SimpleNamespace(key=KEY)
        self.calls = []
        self.permissions = [
            "query-funds", "query-open-trades", "query-closed-trades", "query-ledger",
        ]
        self.orders = {}
        self.balances = {"ZUSD": {"balance": "100", "hold_trade": "5"}}
        self.on_call = None

    def _kraken_private_call(self, method, params, *, category):
        assert category is CATEGORY, "unreviewed category"
        self.calls.append(method)
        if self.on_call:
            self.on_call(method)
        if method == "GetApiKeyInfo":
            assert params == {}
            return {"error": [], "result": {
                "apiKey": KEY, "iban": IBAN, "validUntil": "0",
                "queryFrom": "0", "queryTo": "0",
                "permissions": list(self.permissions),
            }}
        if method == "BalanceEx":
            assert params == {}
            return {"error": [], "result": copy.deepcopy(self.balances)}
        if method == "OpenOrders":
            assert params == {"with_cursor": True, "limit": 50, "trades": True}
            return {"error": [], "result": {
                "open": copy.deepcopy(self.orders), "cursor": {},
            }}
        raise AssertionError("attempted unauthorized private endpoint")


class Ledger:
    def __init__(self):
        self.calls = 0
        self.orders = {}
        self.unresolved = 0

    def __call__(self):
        self.calls += 1
        return {
            "account": "platform:kraken",
            "source": "independent_ledger",
            "provider_id": "reviewed-independent-ledger",
            "snapshot_id": "reviewed-ledger-snapshot",
            "snapshot_complete": True, "outstanding_intents_reconciled": True,
            "unresolved_submission_count": self.unresolved,
            "observed_at_epoch": 1000.0,
            "orders": copy.deepcopy(self.orders),
        }


class TestKrakenRealProviderIntegration(unittest.TestCase):
    def bundle(self, broker, ledger):
        return make_reviewed_kraken_producer_bundle(
            broker, account_scope="platform:kraken",
            approved_api_key_sha256=PIN_KEY,
            approved_iban_sha256=PIN_ACCOUNT,
            reviewed_provider_ids=IDS,
            reviewed_ledger_provider_id="reviewed-independent-ledger",
            independent_open_intents=ledger,
            monitoring_category=CATEGORY,
            independently_reviewed=True,
            clock=lambda: 1001.0,
        )

    def test_real_4_producers_accept_current_consistent_broker_reads(self):
        broker, ledger = Client(), Ledger()
        bundle = self.bundle(broker, ledger)
        self.assertEqual(broker.calls, [])
        rows = {field: bundle[field]() for field in FIELDS}
        self.assertEqual(len(rows), 4)
        self.assertGreaterEqual(broker.calls.count("GetApiKeyInfo"), 6)
        self.assertEqual(broker.calls.count("OpenOrders"), 2)
        self.assertEqual(broker.calls.count("BalanceEx"), 1)
        self.assertEqual(ledger.calls, 2)
        trusted = {field: "reviewed-" + field for field in REQUIRED}
        trusted.update(IDS)
        result = evaluate_pretrade_certificate(
            rows, account="platform:kraken", trusted_provider_ids=trusted,
            now_epoch=1001.0,
        )
        self.assertEqual(set(result["missing"]), set(MISSING_FIELDS))
        self.assertFalse(result["certified"])
        self.assertFalse(result["authorizes_orders"])
        inspected = inspect_authenticated_attestations("platform:kraken", now=1001.0)
        self.assertFalse(inspected["collector_installed"])
        for secret in (PIN_KEY, PIN_ACCOUNT, KEY, IBAN, OID):
            self.assertNotIn(secret, json.dumps(rows))

    def test_order_ledger_disagreement_stops_only_open_order_evidence(self):
        broker, ledger = Client(), Ledger()
        ledger.orders[OID] = {
            "pair": "ETHUSD", "side": "sell", "ordertype": "stop-loss",
            "price": "120", "volume": "0.1", "executed": "0",
        }
        bundle = self.bundle(broker, ledger)
        self.assertTrue(bundle["account_permissions"]()["verified"])
        self.assertTrue(bundle["account_identity"]()["verified"])
        self.assertTrue(bundle["broker_balances"]()["verified"])
        with self.assertRaises(ValueError):
            bundle["open_order_reconciliation"]()

    def test_missing_live_permissions_denies_permissions_evidence(self):
        broker, ledger = Client(), Ledger()
        broker.permissions.remove("query-ledger")
        with self.assertRaises(ValueError):
            self.bundle(broker, ledger)["account_permissions"]()

    def test_transport_switch_denies_balance_evidence(self):
        broker, ledger = Client(), Ledger()
        broker._gateway_only_mode = True
        with self.assertRaises(ValueError):
            self.bundle(broker, ledger)["broker_balances"]()

    def test_wallet_role_switch_denies_identity_evidence(self):
        broker, ledger = Client(), Ledger()
        broker.account_type = "user"
        broker.user_id = "wrong"
        with self.assertRaises(ValueError):
            self.bundle(broker, ledger)["account_identity"]()

    def test_never_turn_partial_evidence_into_full_certificate(self):
        broker, ledger = Client(), Ledger()
        bundle = self.bundle(broker, ledger)
        rows = {name: provider() for name, provider in bundle.items()}
        ids = {field: "reviewed-" + field for field in REQUIRED}
        ids.update(IDS)
        for field in MISSING_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, evaluate_pretrade_certificate(
                    rows, account="platform:kraken", trusted_provider_ids=ids,
                    now_epoch=1001.0,
                )["missing"])


if __name__ == "__main__":
    unittest.main()
