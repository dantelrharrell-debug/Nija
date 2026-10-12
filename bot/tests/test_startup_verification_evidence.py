"""Offline regressions: no runtime bootstrap, credentials or real broker orders."""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "_startup_verification_evidence_offline", BOT / "startup_verification_evidence.py"
)
E = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = E
SPEC.loader.exec_module(E)


class FixtureBrokerType(Enum):
    KRAKEN = "kraken"


class Broker:
    """A fixed authenticated-response fixture; not a network client."""

    broker_type = FixtureBrokerType.KRAKEN
    account_type = types.SimpleNamespace(value="platform")
    account_identifier = "platform"

    def __init__(self):
        self.calls = []
        now = time.time() - 1
        self.responses = {
            "GetApiKeyInfo": {"iban": "AA00 TEST TEST TEST", "apiKey": "fixture-public-key",
                              "permissions": ["query-funds", "query-open-trades", "query-closed-trades",
                                              "query-ledger", "modify-trades", "close-trades"]},
            "QueryOrders": {
                "BUY": {"status": "closed", "descr": {"type": "buy", "pair": "XXBTZUSD", "leverage": "none"},
                        "vol_exec": "0.01000000", "trades": ["TB"]},
                "SELL": {"status": "closed", "descr": {"type": "sell", "pair": "XXBTZUSD", "leverage": "none"},
                         "vol_exec": "0.00900000", "trades": ["TS"]},
            },
            "QueryTrades": {
                "TB": {"ordertxid": "BUY", "type": "buy", "vol": "0.01000000", "time": now,
                       "ledgers": ["BB", "BQ"]},
                "TS": {"ordertxid": "SELL", "type": "sell", "vol": "0.00900000", "time": now,
                       "ledgers": ["SB", "SQ"]},
            },
            "QueryLedgers": {
                "BB": {"refid": "TB", "type": "trade", "asset": "XXBT", "amount": "0.01000000", "fee": "0.00100000"},
                "BQ": {"refid": "TB", "type": "trade", "asset": "ZUSD", "amount": "-10.00000000", "fee": "0.05000000"},
                "SB": {"refid": "TS", "type": "trade", "asset": "XXBT", "amount": "-0.00900000", "fee": "0.00000000"},
                "SQ": {"refid": "TS", "type": "trade", "asset": "ZUSD", "amount": "6.75000000", "fee": "0.03000000"},
            },
            "AddOrder": {"descr": {"order": "validated buy", "close": "validated stop"}},
        }

    def _kraken_private_call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method in {"QueryOrders", "QueryTrades", "QueryLedgers"}:
            ids = params["id" if method == "QueryLedgers" else "txid"].split(",")
            result = {key: self.responses[method][key] for key in ids if key in self.responses[method]}
        else:
            result = self.responses[method]
        return {"error": [], "result": copy.deepcopy(result)}


def extracted(file, names, globals_extra=None):
    tree = ast.parse((BOT / file).read_text())
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    body = []
    for name in names:
        node = functions[name]
        node.decorator_list = []
        # Dependency injection for a lazy import, without importing bot startup.
        node.body = [x for x in node.body if not isinstance(x, ast.ImportFrom)]
        body.append(node)
    env = {"Any": Any, "Dict": Dict, "List": List, "Optional": Optional,
           "logger": logging.getLogger("offline"), "LOGGER": logging.getLogger("offline"),
           "os": os, "threading": threading, "nullcontext": nullcontext,
           "time": types.SimpleNamespace(time=time.time, sleep=lambda _: None),
           "platform_startup_candidates": E.platform_startup_candidates}
    env.update(globals_extra or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(BOT / file), "exec"), env)
    return env


class EvidenceTests(unittest.TestCase):
    def test_identity_is_authenticated_and_redacted(self):
        broker = Broker()
        identity = E.read_startup_broker_identity(broker)
        self.assertEqual(broker.calls, [("GetApiKeyInfo", {})])
        self.assertEqual(len(identity.account_fingerprint), 64)
        self.assertNotIn("fixture-public-key", repr(identity))

    def test_adapter_exception_cannot_expose_credentials(self):
        broker = Broker()
        def broken_call(*_):
            raise RuntimeError("synthetic-private-header-value")
        broker._kraken_private_call = broken_call
        with self.assertRaises(E.StartupEvidenceError) as caught:
            E.read_startup_broker_identity(broker)
        self.assertNotIn("synthetic-private-header-value", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_identity_rejects_missing_account_or_key(self):
        for key in ["iban", "apiKey", "permissions"]:
            with self.subTest(key=key):
                broker = Broker()
                del broker.responses["GetApiKeyInfo"][key]
                with self.assertRaises(E.StartupEvidenceError):
                    E.read_startup_broker_identity(broker)

    def test_other_venue_is_not_silently_used(self):
        broker = Broker()
        broker.broker_type = types.SimpleNamespace(value="coinbase")
        with self.assertRaises(E.StartupEvidenceError):
            E.read_startup_broker_identity(broker)
        self.assertEqual(broker.calls, [])

    def test_readonly_validation_cannot_turn_into_a_real_order(self):
        broker = Broker()
        params = {"pair": "XBTUSD", "type": "buy", "ordertype": "limit", "volume": "0.001",
                  "price": "1000", "validate": False}
        result = E.validate_readonly_startup_order(broker, params)
        self.assertIs(broker.calls[-1][1]["validate"], True)
        self.assertIs(params["validate"], False)
        self.assertIs(result["execution_proof"], False)
        self.assertIs(result["orders_submitted"], False)
        self.assertIs(result["ownership_verified"], False)
        self.assertIs(result["all_in_cost_guaranteed"], False)

    def test_readonly_validation_rejects_unlisted_fields_or_order_id(self):
        params = {"pair": "XBTUSD", "type": "buy", "ordertype": "limit", "volume": "0.001"}
        for change in ["unknown_field", "txid"]:
            with self.subTest(change=change):
                broker = Broker()
                data = dict(params)
                if change == "unknown_field":
                    data["withdraw"] = True
                else:
                    broker.responses["AddOrder"]["txid"] = ["unexpected"]
                with self.assertRaises(E.StartupEvidenceError):
                    E.validate_readonly_startup_order(broker, data)

    def test_exact_base_credit_minus_fee_is_used(self):
        evidence = E.read_startup_fill_evidence(Broker(), "BUY", "BTC-USD", "buy")
        self.assertEqual(evidence.gross_base_quantity, Decimal("0.01"))
        self.assertEqual(evidence.net_base_delta, Decimal("0.009"))
        self.assertEqual(evidence.quote_delta, Decimal("-10.05"))

    def test_exact_sell_evidence_conserves_net_base(self):
        broker = Broker()
        buy = E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")
        sell = E.read_startup_fill_evidence(broker, "SELL", "BTC-USD", "sell")
        self.assertEqual(buy.net_base_delta + sell.net_base_delta, 0)
        self.assertEqual(sell.quote_delta, Decimal("6.72"))

    def test_rejects_incomplete_mismatched_or_nonfinite_evidence(self):
        cases = [
            ("QueryOrders", "BUY", "status", "open"),
            ("QueryOrders", "BUY", "vol_exec", "0.1"),
            ("QueryTrades", "TB", "ordertxid", "other-order"),
            ("QueryTrades", "TB", "time", float("nan")),
            ("QueryTrades", "TB", "ledgers", []),
            ("QueryLedgers", "BB", "refid", "other-trade"),
            ("QueryLedgers", "BB", "fee", "nan"),
            ("QueryLedgers", "BB", "amount", "-0.01"),
            ("QueryLedgers", "BQ", "asset", "USDT"),
        ]
        for method, key, field, value in cases:
            with self.subTest(case=(method, key, field)):
                broker = Broker()
                broker.responses[method][key][field] = value
                with self.assertRaises(E.StartupEvidenceError):
                    E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")

    def test_rejects_pair_side_margin_and_duplicate_trade_links(self):
        for field, value in [("pair", "XETHZUSD"), ("type", "sell"), ("leverage", "5:1")]:
            with self.subTest(field=field):
                broker = Broker()
                broker.responses["QueryOrders"]["BUY"]["descr"][field] = value
                with self.assertRaises(E.StartupEvidenceError):
                    E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")
        broker = Broker()
        broker.responses["QueryOrders"]["BUY"]["trades"] = ["TB", "TB"]
        with self.assertRaises(E.StartupEvidenceError):
            E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")

    def test_query_batches_respect_twenty_id_limit(self):
        broker = Broker()
        ids = [f"T{i}" for i in range(41)]
        broker.responses["QueryTrades"] = {key: {} for key in ids}
        E._read_ids(broker, "QueryTrades", ids, ledgers=True)
        self.assertEqual([len(data["txid"].split(",")) for _, data in broker.calls], [20, 20, 1])

    def test_ledger_queries_use_documented_id_parameter(self):
        broker = Broker()
        E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")
        queries = [data for method, data in broker.calls if method == "QueryLedgers"]
        self.assertEqual(queries, [{"id": "BB,BQ"}])

    def test_platform_mapping_wins_same_venue_collision(self):
        platform = Broker()
        user = Broker()
        user.account_type = types.SimpleNamespace(value="user")
        strategy = types.SimpleNamespace(
            multi_account_manager=types.SimpleNamespace(platform_brokers={"kraken": platform}),
            broker_manager=types.SimpleNamespace(brokers={"kraken": user}, get_primary_broker=lambda: user),
            broker=user,
        )
        env = extracted("runtime_heartbeat_position_cap_failover_v273_patch.py", ["_candidate_brokers"])
        self.assertIs(env["_candidate_brokers"](strategy)["kraken"], platform)

    def test_explicit_user_and_unknown_legacy_adapters_are_excluded(self):
        platform = types.SimpleNamespace()
        user = Broker()
        user.account_type = "user"
        legacy = types.SimpleNamespace()
        got = E.platform_startup_candidates({"p": platform, "u": user, "legacy": legacy}, {"p": platform})
        self.assertEqual(got, {"p": platform})

    def test_v274_fallback_preserves_platform_owner(self):
        platform = Broker()
        user = Broker()
        user.account_type = "user"
        strategy = types.SimpleNamespace(
            multi_account_manager=types.SimpleNamespace(platform_brokers={"kraken": platform}),
            broker_manager=types.SimpleNamespace(brokers={"kraken": user}, get_primary_broker=lambda: user),
            broker=user,
        )
        def unavailable_module(_):
            raise ImportError("fixture: v273 unavailable")
        env = extracted("runtime_heartbeat_live_venue_selection_v274_patch.py", ["_candidate_brokers"],
                        {"importlib": types.SimpleNamespace(import_module=unavailable_module)})
        self.assertIs(env["_candidate_brokers"](strategy)["kraken"], platform)


class DurableAttemptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "attempts.db"
        self.identity = E.read_startup_broker_identity(Broker())

    def tearDown(self):
        self.directory.cleanup()

    def test_one_claim_survives_new_connection_and_key_rotation(self):
        self.assertTrue(E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path))
        rotated = E.StartupBrokerIdentity(self.identity.account_fingerprint, "b" * 64, time.time())
        self.assertFalse(E.claim_startup_attempt(rotated, "renamed-platform", "ETH-USD", path=self.path))

    def test_parallel_claims_allow_one_attempt(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(
                lambda _: E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path), range(8)
            ))
        self.assertEqual(sum(values), 1)

    def test_completed_or_unknown_outcome_does_not_rearm(self):
        for state in ["state_unknown", "completed"]:
            with self.subTest(state=state):
                self.assertTrue(E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path))
                E.record_startup_attempt(self.identity, state, entry_order_id="BUY", path=self.path)
                self.assertFalse(E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path))
                self.path.unlink()

    def test_relative_stale_and_unwritable_attempt_storage_fail_closed(self):
        stale = E.StartupBrokerIdentity(self.identity.account_fingerprint, "b" * 64, time.time() - 60)
        for identity, path in [(self.identity, Path("relative.db")), (stale, self.path)]:
            with self.subTest(path=str(path)), self.assertRaises(E.StartupEvidenceError):
                E.claim_startup_attempt(identity, "platform", "BTC-USD", path=path)
        blocked = Path(self.directory.name) / "file"
        blocked.write_text("not a directory")
        with self.assertRaises(E.StartupEvidenceError):
            E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=blocked / "db")

    def test_unreconciled_attempt_withholds_execution_proof(self):
        self.assertTrue(E.startup_attempts_allow_execution_proof(path=self.path))
        E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
        for state in ["claimed", "entry_pending", "entry_filled", "exit_pending", "state_unknown"]:
            E.record_startup_attempt(self.identity, state, path=self.path)
            self.assertFalse(E.startup_attempts_allow_execution_proof(path=self.path))
        E.record_startup_attempt(self.identity, "completed", path=self.path)
        self.assertTrue(E.startup_attempts_allow_execution_proof(path=self.path))

    def test_corrupt_attempt_store_cannot_publish_proof(self):
        self.path.write_text("not SQLite")
        self.assertFalse(E.startup_attempts_allow_execution_proof(path=self.path))

    def test_canonical_marker_cannot_publish_mid_round_trip(self):
        E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
        env = extracted("runtime_execution_position_readiness_v346_patch.py",
                        ["_write_confirmed_fill_marker_locked"], {
                            "Mapping": dict, "importlib": importlib, "MARKER": "fixture",
                            "startup_attempts_allow_execution_proof": E.startup_attempts_allow_execution_proof,
                        })
        with patch.dict(os.environ, {"NIJA_STARTUP_ATTEMPT_DB": str(self.path)}), patch.dict(
            sys.modules, {"bot": types.ModuleType("bot"), "bot.startup_verification_evidence": E}
        ):
            self.assertFalse(env["_write_confirmed_fill_marker_locked"](
                result={"order_id": "BUY"}, symbol="BTC-USD", side="buy",
                fill_price=1000.0, filled_usd=10.0,
            ))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        # Executing the extracted order flow must never import bot bootstrap or
        # start runtime patch workers, including on a complete CI checkout.
        state_machine = types.ModuleType("bot.trading_state_machine")
        state_machine.report_execution_anomaly = lambda *_: None
        self.runtime_imports = patch.dict(sys.modules, {"bot.trading_state_machine": state_machine})
        self.runtime_imports.start()
        self.broker = Broker()
        identity = E.read_startup_broker_identity(self.broker)
        self.environment = patch.dict(os.environ, {
            "NIJA_STARTUP_ATTEMPT_DB": str(Path(self.directory.name) / "attempts.db"),
            "NIJA_HEARTBEAT_ACCOUNT_FINGERPRINT": identity.account_fingerprint,
        })
        self.environment.start()
        self.submits = []
        self.markers = []
        self.payloads = [dict(status="filled", order_id="BUY", filled_price=1000.0, filled_size_usd=10.0),
                         dict(status="filled", order_id="SELL", filled_price=750.0, filled_size_usd=6.75)]
        def submit(**kwargs):
            self.submits.append(kwargs)
            return dict(self.payloads[len(self.submits) - 1])
        extra = {name: getattr(E, name) for name in ["StartupEvidenceError", "claim_startup_attempt",
                 "read_startup_broker_identity", "read_startup_fill_evidence", "record_startup_attempt"]}
        extra.update(_HEARTBEAT_TRADE_SYMBOL="BTC-USD", _HEARTBEAT_CONFIRMED_FILL_STATUS="filled",
                     _HEARTBEAT_ACKNOWLEDGED_STATUSES=frozenset({"pending", "submitted", "accepted", "open"}),
                     format_broker_identity=lambda _: "kraken:platform",
                     _heartbeat_required_stage=lambda: "FILL_VERIFY",
                     _heartbeat_stage_is_sufficient=lambda stage, required: stage == required,
                     _heartbeat_rate_limited_info=lambda *_: None,
                     startup_execution_probe_scope=lambda _: nullcontext(),
                     runtime_correlation_scope=lambda **_: nullcontext(), submit_market_order_via_pipeline=submit,
                     _bounded_heartbeat_market_discovery=lambda *_: [])
        self.env = extracted("trading_strategy.py", ["_positive_float", "_heartbeat_result_is_confirmed_fill",
                             "_heartbeat_result_has_confirmed_submission", "_execute_heartbeat_trade"], extra)
        self.strategy = types.SimpleNamespace(_get_heartbeat_broker=lambda: self.broker,
                         _resolve_heartbeat_trade_amount_usd=lambda _: 10.0,
                         _heartbeat_auth_verify=lambda _: (True, "fixture-auth"),
                         _persist_heartbeat_marker=lambda **kwargs: self.markers.append(kwargs))

    def tearDown(self):
        self.runtime_imports.stop()
        self.environment.stop()
        self.directory.cleanup()

    def test_closes_exact_fee_adjusted_base_and_explicit_exit(self):
        self.assertTrue(self.env["_execute_heartbeat_trade"](self.strategy))
        close = self.submits[1]
        self.assertEqual(close["quantity"], 0.009)
        self.assertEqual(close["size_type"], "base")
        self.assertEqual(close["intent_type"], "exit")
        self.assertEqual(close["position_effect"], "close")
        self.assertTrue(close["reduce_only_override"])
        self.assertEqual(len(self.markers), 1)
        self.assertLess(self.markers[0]["details"]["broker_execution_epoch"], time.time())
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(len(self.submits), 2)

    def test_missing_or_wrong_account_lock_prevents_entry(self):
        for value in ["", "b" * 64]:
            with self.subTest(value=value), patch.dict(os.environ, {"NIJA_HEARTBEAT_ACCOUNT_FINGERPRINT": value}):
                self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(self.submits, [])

    def test_missing_ledger_permission_prevents_entry(self):
        self.broker.responses["GetApiKeyInfo"]["permissions"].remove("query-ledger")
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(self.submits, [])

    def test_pending_buy_is_consumed_and_never_retried(self):
        self.payloads[0] = dict(status="pending", order_id="BUY")
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(len(self.submits), 1)
        self.assertEqual(self.markers, [])

    def test_missing_fee_evidence_does_not_guess_quantity_or_publish_proof(self):
        del self.broker.responses["QueryLedgers"]["BB"]["fee"]
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(len(self.submits), 1)
        self.assertEqual(self.markers, [])

    def test_partial_close_leaves_proof_unpublished(self):
        self.broker.responses["QueryOrders"]["SELL"]["vol_exec"] = "0.00450000"
        self.broker.responses["QueryTrades"]["TS"]["vol"] = "0.00450000"
        self.broker.responses["QueryLedgers"]["SB"]["amount"] = "-0.00450000"
        self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(len(self.submits), 2)
        self.assertEqual(self.markers, [])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
