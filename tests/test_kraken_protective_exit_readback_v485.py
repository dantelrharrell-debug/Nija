"""Offline regression for Kraken protective-exit readback v485."""
import copy
import hashlib
import sys
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = pkg

from bot.kraken_protective_exit_readback_v485 import (
    KrakenProtectionDenied, make_kraken_protective_exit_provider,
)

KEY = "synthetic-key"
IBAN = "AA00 TEST"
KEY_PIN = hashlib.sha256(KEY.encode()).hexdigest()
IBAN_PIN = hashlib.sha256(("kraken\\0" + IBAN).encode()).hexdigest()
CATEGORY = object()
STOP = "OABCDE-ABCDE-ABCDEF"
PROFIT = "OBCDEF-BCDEF-BCDEFG"


class Broker:
    connected = True
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    _gateway_url = ""
    _gateway_only_mode = False

    def __init__(self):
        self.api = types.SimpleNamespace(key=KEY)
        self.calls = []
        self.orders = {
            STOP: self.order("stop-loss", "110", "1"),
            PROFIT: self.order("take-profit", "160", "1"),
        }

    @staticmethod
    def order(kind, price, vol):
        return {
            "status": "open", "vol": vol, "vol_exec": "0",
            "descr": {"pair": "ETHUSD", "type": "sell", "ordertype": kind, "price": price},
        }

    def _kraken_private_call(self, method, params, *, category):
        assert category is CATEGORY
        self.calls.append(method)
        if method == "GetApiKeyInfo":
            return {"error": [], "result": {
                "apiKey": KEY, "iban": IBAN, "validUntil": "0",
            }}
        if method == "OpenOrders":
            assert params == {"with_cursor": True, "limit": 50, "trades": True}
            return {"error": [], "result": {
                "open": copy.deepcopy(self.orders), "cursor": {},
            }}
        raise AssertionError("non-read-only endpoint requested")


class Ledger:
    def __init__(self):
        self.positions = {
            "lot-1": {
                "pair": "ETHUSD", "side": "long", "quantity": "1",
                "stop_order_id": STOP, "take_profit_order_id": PROFIT,
            }
        }
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {
            "account": "platform:kraken",
            "provider_id": "independent-ledger",
            "source": "independent_ledger",
            "snapshot_complete": True,
            "fills_reconciled": True,
            "positions_reconciled": True,
            "snapshot_id": "snapshot-1",
            "observed_at_epoch": 1000.0,
            "positions": copy.deepcopy(self.positions),
        }


def build(broker, ledger):
    return make_kraken_protective_exit_provider(
        broker, account_scope="platform:kraken",
        approved_api_key_sha256=KEY_PIN,
        approved_iban_sha256=IBAN_PIN,
        reviewed_provider_id="broker-protection",
        reviewed_ledger_provider_id="independent-ledger",
        independent_positions=ledger, monitoring_category=CATEGORY,
        clock=lambda: 1001.0,
    )


class TestProtection(unittest.TestCase):
    def test_verified_protection_read_only(self):
        broker, ledger = Broker(), Ledger()
        provider = build(broker, ledger)
        self.assertEqual(broker.calls, [])
        result = provider()
        self.assertTrue(result["verified"])
        self.assertFalse(result["authorizes_orders"])
        self.assertEqual(broker.calls.count("OpenOrders"), 2)
        self.assertEqual(ledger.calls, 2)

    def test_missing_stop_denied(self):
        broker, ledger = Broker(), Ledger()
        del broker.orders[STOP]
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()

    def test_partial_stop_denied(self):
        broker, ledger = Broker(), Ledger()
        broker.orders[STOP]["vol"] = "0.5"
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()

    def test_missing_profit_denied(self):
        broker, ledger = Broker(), Ledger()
        del broker.orders[PROFIT]
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()

    def test_unreconciled_ledger_denied(self):
        broker, ledger = Broker(), Ledger()
        ledger.positions = {}
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()

    def test_wrong_scope_denied(self):
        with self.assertRaises(KrakenProtectionDenied):
            make_kraken_protective_exit_provider(
                Broker(), account_scope="user:1:kraken",
                approved_api_key_sha256=KEY_PIN,
                approved_iban_sha256=IBAN_PIN,
                reviewed_provider_id="broker-protection",
                reviewed_ledger_provider_id="independent-ledger",
                independent_positions=Ledger(), monitoring_category=CATEGORY,
            )


if __name__ == "__main__":
    unittest.main()
