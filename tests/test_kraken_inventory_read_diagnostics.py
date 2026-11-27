"""Regression tests for redacted, read-only Kraken inventory diagnostics."""
import unittest

from bot.kraken_current_inventory import InventoryDenied, read_current_inventory


class Broker:
    broker_type = "kraken"
    account_type = "platform"
    user_id = None
    connected = True
    _gateway_url = ""
    _gateway_only_mode = False

    def __init__(self, failure=None):
        self.api = object()
        self.failure = failure
        self.calls = []

    def _kraken_private_call(self, endpoint, params, *, category):
        self.calls.append((endpoint, params, category))
        if endpoint == "OpenOrders" and self.failure == "timeout":
            raise TimeoutError("synthetic-private-error-value")
        results = {
            "BalanceEx": {"TESTASSET": {"balance": "1", "hold_trade": "0"}},
            "OpenOrders": {"open": {}},
            "OpenPositions": {},
        }
        if endpoint == "OpenOrders" and self.failure == "shape":
            return {"error": ["synthetic-private-response-value"], "result": {}}
        return {"error": [], "result": results[endpoint]}


class InventoryDiagnosticsTest(unittest.TestCase):
    def test_success_reports_only_safe_labels_in_call_order(self):
        broker = Broker()
        category = object()
        with self.assertLogs("bot.kraken_current_inventory", "INFO") as logs:
            result = read_current_inventory(broker, category)
        self.assertTrue(result["inventory_read_succeeded"])
        self.assertEqual(list(result["observations"]), ["BalanceEx", "OpenOrders", "OpenPositions"])
        self.assertEqual(broker.calls, [(endpoint, {}, category) for endpoint in result["observations"]])
        self.assertEqual([r.getMessage() for r in logs.records], [
            f"KRAKEN_INVENTORY_READ endpoint={endpoint} phase={phase}"
            for endpoint in result["observations"] for phase in ("started", "validated")
        ])

    def test_transport_failure_does_not_leak_or_continue(self):
        broker = Broker("timeout")
        with self.assertLogs("bot.kraken_current_inventory", "INFO") as logs:
            with self.assertRaises(TimeoutError):
                read_current_inventory(broker, object())
        self.assertEqual([c[0] for c in broker.calls], ["BalanceEx", "OpenOrders"])
        self.assertEqual([r.getMessage() for r in logs.records][-1],
                         "KRAKEN_INVENTORY_READ endpoint=OpenOrders phase=raised")
        self.assertFalse(any(r.exc_info for r in logs.records))
        self.assertNotIn("synthetic-private-error-value", "\n".join(logs.output))

    def test_rejected_payload_is_never_logged_as_validated(self):
        broker = Broker("shape")
        with self.assertLogs("bot.kraken_current_inventory", "INFO") as logs:
            with self.assertRaisesRegex(InventoryDenied, "^inventory_response_invalid$"):
                read_current_inventory(broker, object())
        self.assertEqual([c[0] for c in broker.calls], ["BalanceEx", "OpenOrders"])
        self.assertEqual([r.getMessage() for r in logs.records][-1],
                         "KRAKEN_INVENTORY_READ endpoint=OpenOrders phase=started")
        self.assertNotIn("synthetic-private-response-value", "\n".join(logs.output))
