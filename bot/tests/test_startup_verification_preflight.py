"""Isolated regression suite for read-only Kraken startup preflight.

Uses synthetic adapter responses only. No runtime bootstrap, credentials, or live orders.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("bot")
package.__path__ = [str(BOT)]
sys.modules["bot"] = package
for name in ("startup_verification_evidence", "startup_verification_plan", "startup_verification_preflight"):
    spec = importlib.util.spec_from_file_location("bot." + name, BOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

P = sys.modules["bot.startup_verification_plan"]
V = sys.modules["bot.startup_verification_preflight"]


class StartupPreflightTests(unittest.TestCase):
    def setUp(self):
        self.plan = P.StartupVerificationPlan(
            "a" * 64, "b" * 128, "BTC-USD", "XXBTZUSD", "25", "1000", "0.020",
            "0.01", "0.20", "950", "900", "990", "0.001", "0.001", "1",
            time.time() + 300,
        )
        self.calls = []
        self.nonce_assertions = 0
        self.responses = {
            "BalanceEx": {"ZUSD": {"balance": "30", "hold_trade": "2", "credit": "1000"}},
            "OpenOrders": {"open": {}},
            "OpenPositions": {},
            "TradeVolume": {"fees": {"XXBTZUSD": {"maxfee": "0.60"}}},
            "AddOrder": {"descr": {"order": "synthetic entry", "close": "synthetic native stop"}},
        }
        self.broker = types.SimpleNamespace(
            account_type="platform", _kraken_private_call=self.private_call
        )
        self.pair = {
            "pair": "XXBTZUSD", "quote": "ZUSD", "status": "online",
            "lot_decimals": 3, "pair_decimals": 2, "tick_size": "0.01",
            "ordermin": "0.001", "costmin": "1", "observed_at_epoch": time.time(),
        }
        self.identity = types.SimpleNamespace(
            account_fingerprint="a" * 64, api_key_fingerprint="b" * 128,
            observed_at_epoch=time.time()
        )
        mocked = patch.object(V, "read_startup_broker_identity", return_value=self.identity)
        mocked.start()
        self.addCleanup(mocked.stop)

    def private_call(self, method, params):
        self.calls.append((method, dict(params)))
        return {"error": [], "result": self.responses[method]}

    def assert_owner(self):
        self.nonce_assertions += 1

    def run_check(self, **changes):
        kwargs = {
            "statement_account_fingerprint": "a" * 64,
            "read_asset_pair": lambda _: self.pair,
            "assert_nonce_owner": self.assert_owner,
        }
        kwargs.update(changes)
        return V.run_kraken_startup_preflight(self.broker, self.plan, **kwargs)

    def assert_no_order_validation(self):
        self.assertNotIn("AddOrder", [name for name, _ in self.calls])

    def test_validation_is_not_execution_or_proof(self):
        report = self.run_check()
        self.assertTrue(report.validation_only)
        self.assertFalse(report.orders_submitted)
        self.assertFalse(report.execution_ready)
        self.assertFalse(report.live_transport_verified)
        self.assertEqual(report.available_cash_usd, "28")
        method, params = self.calls[-1]
        self.assertEqual(method, "AddOrder")
        self.assertIs(params["validate"], True)
        self.assertEqual(params["timeinforce"], "FOK")
        self.assertEqual(params["close[ordertype]"], "stop-loss-limit")
        self.assertEqual(params["volume"], "0.020")
        self.assertGreaterEqual(self.nonce_assertions, len(self.calls) + 3)

    def test_wrong_account_or_user_scope_stops_before_api(self):
        with self.assertRaisesRegex(V.StartupPreflightError, "statement_account"):
            self.run_check(statement_account_fingerprint="c" * 64)
        self.assertEqual(self.calls, [])
        self.broker.account_type = "user"
        with self.assertRaisesRegex(V.StartupPreflightError, "explicit_platform"):
            self.run_check()
        self.assertEqual(self.calls, [])

    def test_credit_does_not_fund_spot_preflight(self):
        self.responses["BalanceEx"]["ZUSD"]["balance"] = "1"
        with self.assertRaisesRegex(V.StartupPreflightError, "cash_excluding_credit"):
            self.run_check()
        self.assert_no_order_validation()

    def test_holds_and_used_credit_are_subtracted(self):
        self.responses["BalanceEx"]["ZUSD"]["credit_used"] = "27"
        with self.assertRaises(V.StartupPreflightError):
            self.run_check()
        self.assert_no_order_validation()

    def test_market_pair_minima_tick_and_age_fail_closed(self):
        for field, change in [
            ("ordermin", "0.002"), ("costmin", "2"), ("lot_decimals", 4),
            ("status", "cancel_only"), ("quote", "ZEUR"), ("pair", "OTHER"),
            ("observed_at_epoch", time.time() - 31), ("tick_size", "3"),
        ]:
            with self.subTest(field=field):
                original = self.pair[field]
                self.pair[field] = change
                with self.assertRaises(V.StartupPreflightError):
                    self.run_check()
                self.assert_no_order_validation()
                self.pair[field] = original

    def test_maximum_fee_rate_is_binding(self):
        self.responses["TradeVolume"]["fees"]["XXBTZUSD"]["maxfee"] = "1.1"
        with self.assertRaisesRegex(V.StartupPreflightError, "fee_bound"):
            self.run_check()
        self.assert_no_order_validation()

    def test_missing_fee_data_cannot_pass(self):
        self.responses["TradeVolume"] = {}
        with self.assertRaisesRegex(V.StartupPreflightError, "fee_data"):
            self.run_check()
        self.assert_no_order_validation()

    def test_existing_open_orders_or_margin_positions_block(self):
        for key, value in [
            ("OpenOrders", {"open": {"existing": {}}}),
            ("OpenPositions", {"position": {"vol": "1"}}),
        ]:
            with self.subTest(method=key):
                original = self.responses[key]
                self.responses[key] = value
                with self.assertRaises(V.StartupPreflightError):
                    self.run_check()
                self.assert_no_order_validation()
                self.responses[key] = original

    def test_invalid_broker_response_and_exception_are_redacted(self):
        for response in [{"error": ["private-sensitive"]}, {"result": []}, {}]:
            self.broker._kraken_private_call = lambda method, params: response
            with self.assertRaises(V.StartupPreflightError) as exc:
                self.run_check()
            self.assertNotIn("private-sensitive", str(exc.exception))
        def raises(method, params):
            self.calls.append((method, dict(params)))
            raise RuntimeError("synthetic-secret")
        self.broker._kraken_private_call = raises
        with self.assertRaises(V.StartupPreflightError) as exc:
            self.run_check()
        self.assertNotIn("synthetic-secret", str(exc.exception))

    def test_unexpected_order_id_from_validation_is_rejected(self):
        self.responses["AddOrder"]["txid"] = ["unexpected"]
        with self.assertRaisesRegex(V.StartupPreflightError, "unexpected_order_id"):
            self.run_check()

    def test_missing_native_protection_cannot_pass(self):
        for descr in [
            None, [], {}, {"order": []},
            {"order": "entry", "close": None},
            {"order": "entry", "close": " "},
        ]:
            with self.subTest(description=descr):
                self.responses["AddOrder"] = {"descr": descr}
                with self.assertRaises(V.StartupPreflightError):
                    self.run_check()

    def test_rotated_key_blocks_native_validation(self):
        original = self.identity
        rotated = types.SimpleNamespace(
            account_fingerprint=original.account_fingerprint,
            api_key_fingerprint="c" * 128,
            observed_at_epoch=time.time(),
        )
        with patch.object(V, "read_startup_broker_identity",
                          side_effect=[original, rotated]):
            with self.assertRaisesRegex(V.StartupPreflightError, "key_changed"):
                self.run_check()
        self.assert_no_order_validation()

    def test_expired_plan_rejects_before_api(self):
        self.plan = replace(self.plan, expires_at_epoch=time.time() - 1)
        with self.assertRaises(V.StartupPreflightError):
            self.run_check()
        self.assertEqual(self.calls, [])

    def test_real_order_is_forbidden_and_no_retry(self):
        for flag in [False, "true", None]:
            with self.assertRaisesRegex(V.StartupPreflightError, "real_order"):
                V._read(self.broker, "AddOrder", {"validate": flag}, self.assert_owner)
        self.assertEqual(self.calls, [])

    def test_unapproved_api_method_is_forbidden(self):
        with self.assertRaisesRegex(V.StartupPreflightError, "method_forbidden"):
            V._read(self.broker, "CancelAll", {}, self.assert_owner)
        self.assertEqual(self.calls, [])

    def test_nonce_owner_denial_prevents_all_api_calls(self):
        def denied():
            raise RuntimeError("writer/nonce ownership missing")
        with self.assertRaises(RuntimeError):
            self.run_check(assert_nonce_owner=denied)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
