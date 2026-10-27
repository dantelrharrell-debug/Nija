"""Offline Kraken v482 readback tests, no broker credentials or network."""
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

# v480 identity has its own regressions. Stub only that already-reviewed boundary.
stub = types.ModuleType("bot.kraken_authenticated_identity_v480")
KEY = "synthetic-key"
PIN = hashlib.sha256(KEY.encode()).hexdigest()
IBAN = hashlib.sha256(b"kraken\0synthetic-wallet").hexdigest()
CATEGORY = object()
ORDER = "OABCDE-ABCDE-ABCDEF"

def identity(broker, *, account_scope, approved_iban_sha256,
             approved_api_key_sha256, reviewed_provider_id, monitoring_category, clock):
    if approved_iban_sha256 != IBAN or approved_api_key_sha256 != PIN or monitoring_category is not CATEGORY:
        raise ValueError("independently_reviewed_identity_required")
    def observe():
        broker.identity_reads += 1
        if broker.scope != account_scope or broker.key != KEY or broker.connected is not True:
            raise ValueError("identity_mismatch")
        return {"account": account_scope, "verified": True}
    return observe
stub.make_kraken_account_identity_provider = identity
sys.modules[stub.__name__] = stub

from bot.kraken_authenticated_open_order_reconciliation_v482 import (  # noqa: E402
    KrakenOpenOrderDenied, make_kraken_open_order_reconciliation_provider,
)

def orders_row(vol="0.020", pair="ETHUSD", status="open"):
    return {"status": status, "descr": {"pair": pair, "type": "sell", "ordertype": "stop-loss", "price": "123.0"},
            "vol": vol, "vol_exec": "0.0"}

class Broker:
    connected = True
    scope = "platform:kraken"
    key = KEY
    def __init__(self):
        self.orders = {ORDER: orders_row()}
        self.calls = 0
        self.identity_reads = 0
        self.callback = None
    def _kraken_private_call(self, method, params, *, category):
        assert method == "OpenOrders" and category is CATEGORY
        self.calls += 1
        if self.callback:
            return self.callback(params)
        return {"error": [], "result": {"open": copy.deepcopy(self.orders), "cursor": {}}}

class Ledger:
    def __init__(self):
        self.rows = {ORDER: {"pair": "XETHZUSD", "side": "sell", "ordertype": "stop-loss",
                              "price": "123", "volume": "0.02", "executed": "0"}}
        self.at = 1000.0
        self.unresolved = 0
        self.complete = True
        self.scope = "platform:kraken"
        self.calls = 0
        self.callback = None
    def __call__(self):
        self.calls += 1
        if self.callback:
            self.callback()
        return {"account": self.scope, "source": "independent_ledger",
                "provider_id": "approved-ledger", "snapshot_complete": self.complete,
                "outstanding_intents_reconciled": True, "unresolved_submission_count": self.unresolved,
                "observed_at_epoch": self.at, "snapshot_id": "reviewed-snapshot-id",
                "orders": copy.deepcopy(self.rows)}

class TestReadback(unittest.TestCase):
    def provider(self, b, l, **overrides):
        opts = dict(account_scope="platform:kraken", approved_iban_sha256=IBAN,
                    approved_api_key_sha256=PIN, reviewed_provider_id="approved-broker",
                    reviewed_ledger_provider_id="approved-ledger", independent_open_intents=l,
                    monitoring_category=CATEGORY, clock=lambda: 1000.1)
        opts.update(overrides)
        return make_kraken_open_order_reconciliation_provider(b, **opts)
    def denied(self, b, l, **kwargs):
        with self.assertRaises(KrakenOpenOrderDenied):
            self.provider(b, l, **kwargs)()
    def test_exact_match_and_no_side_effects(self):
        b, l = Broker(), Ledger()
        provider = self.provider(b, l)
        self.assertEqual(b.calls, 0)
        result = provider()
        self.assertTrue(result["verified"])
        self.assertTrue(result["provenance"]["complete_pagination_verified"])
        self.assertFalse(result["authorizes_orders"])
        self.assertEqual((b.calls, l.calls, b.identity_reads), (2, 2, 2))
        for value in (ORDER, "XETHZUSD", PIN, IBAN, KEY, "0.02"):
            self.assertNotIn(value, json.dumps(result))
    def test_empty_only_when_independent_ledger_complete(self):
        b, l = Broker(), Ledger()
        b.orders.clear(); l.rows.clear()
        self.assertTrue(self.provider(b, l)()["verified"])
        l.unresolved = 1
        self.denied(b, l)
    def test_broker_mismatch_denied(self):
        changes = [
            lambda b, l: b.orders.clear(),
            lambda b, l: l.rows.clear(),
            lambda b, l: b.orders[ORDER].update(vol="0.03"),
            lambda b, l: b.orders[ORDER].update(vol_exec="0.01"),
            lambda b, l: b.orders[ORDER]["descr"].update(pair="BTCUSD"),
            lambda b, l: b.orders[ORDER]["descr"].update(price="121"),
            lambda b, l: b.orders[ORDER]["descr"].update(ordertype="limit"),
            lambda b, l: b.orders[ORDER].update(status="closed"),
        ]
        for change in changes:
            b, l = Broker(), Ledger()
            change(b, l)
            with self.subTest(change=change):
                self.denied(b, l)
    def test_untrusted_snapshot_denied_before_api(self):
        changes = [
            lambda l: setattr(l, "at", 939.0),
            lambda l: setattr(l, "at", 1002.0),
            lambda l: setattr(l, "complete", False),
            lambda l: setattr(l, "scope", "user:wrong:kraken"),
            lambda l: setattr(l, "unresolved", 1),
            lambda l: setattr(l, "unresolved", False),
        ]
        for change in changes:
            b, l = Broker(), Ledger()
            change(l)
            with self.subTest(change=change):
                self.denied(b, l)
                self.assertEqual(b.calls, 0)
    def test_malformed_volume_denied(self):
        for value in ("-1", "NaN", "Infinity", "1e999", "0", True, None):
            b, l = Broker(), Ledger()
            b.orders[ORDER]["vol"] = value
            with self.subTest(value=value):
                self.denied(b, l)
    def test_changing_broker_or_ledger_denied(self):
        b, l = Broker(), Ledger()
        def changed_broker(params):
            if b.calls == 2:
                b.orders[ORDER]["vol"] = "1"
            return {"error": [], "result": {"open": copy.deepcopy(b.orders), "cursor": {}}}
        b.callback = changed_broker
        self.denied(b, l)
        b, l = Broker(), Ledger()
        def changed_ledger():
            if l.calls == 2:
                l.rows[ORDER]["price"] = "4"
        l.callback = changed_ledger
        self.denied(b, l)
    def test_scope_change_and_latency_denied(self):
        b, l = Broker(), Ledger()
        def lose_scope(params):
            if b.calls == 2:
                b.scope = "user:other:kraken"
            return {"error": [], "result": {"open": copy.deepcopy(b.orders), "cursor": {}}}
        b.callback = lose_scope
        self.denied(b, l)
        b, l = Broker(), Ledger()
        ticks = iter([1000., 1000., 1000., 1061.])
        self.denied(b, l, clock=lambda: next(ticks))
    def test_pagination_duplicate_missing_replay_and_error_denied(self):
        def make_page(next_value, payload=None):
            return {"error": [], "result": {"open": payload or {ORDER: orders_row()},
                                              "cursor": {"next": next_value}}}
        for callback in (
            lambda params: {"error": [], "result": {"open": {}}},
            lambda params: {"error": ["secret upstream problem"], "result": {}},
            lambda params: make_page("repeat"),
        ):
            b, l = Broker(), Ledger()
            b.callback = callback
            with self.subTest(callback=callback):
                self.denied(b, l)
    def test_multi_page_complete_and_exact(self):
        b, l = Broker(), Ledger()
        other = "OABCDE-ABCDF-ABCDEF"
        l.rows[other] = copy.deepcopy(l.rows[ORDER])
        def pages(params):
            if "cursor" not in params:
                return {"error": [], "result": {"open": {ORDER: orders_row()},
                                                  "cursor": {"next": "second"}}}
            return {"error": [], "result": {"open": {other: orders_row()}, "cursor": {}}}
        b.callback = pages
        self.assertTrue(self.provider(b, l)()["verified"])
        self.assertEqual(b.calls, 4)
    def test_separate_pins_and_redaction(self):
        b, l = Broker(), Ledger()
        with self.assertRaises(KrakenOpenOrderDenied):
            self.provider(b, l, reviewed_ledger_provider_id="approved-broker")
        with self.assertRaises(ValueError):
            self.provider(b, l, approved_api_key_sha256="unreviewed")
        b.callback = lambda params: (_ for _ in ()).throw(RuntimeError("secret private credentials"))
        with self.assertRaises(KrakenOpenOrderDenied) as error:
            self.provider(b, l)()
        self.assertNotIn("secret", str(error.exception))
        self.assertIsNone(error.exception.__cause__)

if __name__ == "__main__":
    unittest.main()
