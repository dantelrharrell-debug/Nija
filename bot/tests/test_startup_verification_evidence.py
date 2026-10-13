"""Offline regressions: no runtime bootstrap, credentials or real broker orders."""
from __future__ import annotations

import ast
import copy
import importlib
import json
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
from collections.abc import Mapping
from contextlib import nullcontext
from decimal import Decimal
from enum import Enum
from functools import wraps
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
                "TB": {"ordertxid": "BUY", "type": "buy", "vol": "0.01000000", "time": now},
                "TS": {"ordertxid": "SELL", "type": "sell", "vol": "0.00900000", "time": now},
            },
            "QueryLedgers": {
                "BB": {"refid": "TB", "type": "trade", "asset": "XXBT", "amount": "0.01000000", "fee": "0.00100000"},
                "BQ": {"refid": "TB", "type": "trade", "asset": "ZUSD", "amount": "-10.00000000", "fee": "0.05000000"},
                "SB": {"refid": "TS", "type": "trade", "asset": "XXBT", "amount": "-0.00900000", "fee": "0.00000000"},
                "SQ": {"refid": "TS", "type": "trade", "asset": "ZUSD", "amount": "6.75000000", "fee": "0.03000000"},
            },
            "AddOrder": {"descr": {"order": "validated buy", "close": "validated stop"}},
        }
        for row in self.responses["QueryLedgers"].values():
            row["time"] = now

    def _kraken_private_call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "Ledgers":
            rows = {k: v for k, v in self.responses["QueryLedgers"].items()
                    if params["start"] < v.get("time", 0) <= params["end"]}
            page = list(rows.items())[params["ofs"]:params["ofs"] + 50]
            result = {"ledger": dict(page), "count": len(rows)}
        elif method in {"QueryOrders", "QueryTrades", "QueryLedgers"}:
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
        for change in ["unknown_field", "txid", "empty_txid"]:
            with self.subTest(change=change):
                broker = Broker()
                data = dict(params)
                if change == "unknown_field":
                    data["withdraw"] = True
                elif change == "empty_txid":
                    broker.responses["AddOrder"]["txid"] = []
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
        E._read_ids(broker, "QueryLedgers", ["BB", "BQ"])
        queries = [data for method, data in broker.calls if method == "QueryLedgers"]
        self.assertEqual(queries, [{"id": "BB,BQ"}])

    def test_real_trade_schema_without_ledger_ids_uses_exact_refid_history(self):
        broker = Broker()
        result = E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")
        self.assertEqual(result.net_base_delta, Decimal("0.009"))
        self.assertTrue(any(method == "Ledgers" for method, _ in broker.calls))
        self.assertFalse(any("ledgers" in params for _, params in broker.calls))

    def test_paged_ledger_history_keeps_only_exact_trade_references(self):
        broker = Broker()
        epoch = broker.responses["QueryTrades"]["TB"]["time"]
        unrelated = {f"OTHER{i}": {"refid": f"TOTHER{i}", "time": epoch, "type": "trade"}
                     for i in range(52)}
        broker.responses["QueryLedgers"] = {**unrelated, **broker.responses["QueryLedgers"]}
        result = E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")
        self.assertEqual(result.quote_delta, Decimal("-10.05"))
        self.assertEqual([p["ofs"] for m, p in broker.calls if m == "Ledgers"], [0, 50])

    def test_ledger_history_volume_limit_fails_closed(self):
        broker = Broker()
        epoch = broker.responses["QueryTrades"]["TB"]["time"]
        broker.responses["QueryLedgers"].update(
            {f"OTHER{i}": {"refid": f"TOTHER{i}", "time": epoch, "type": "trade"} for i in range(401)}
        )
        with self.assertRaises(E.StartupEvidenceError):
            E.read_startup_fill_evidence(broker, "BUY", "BTC-USD", "buy")

    def test_platform_mapping_wins_same_venue_collision(self):
        platform = Broker()
        user = Broker()
        user.account_type = types.SimpleNamespace(value="user")
        strategy = types.SimpleNamespace(
            multi_account_manager=types.SimpleNamespace(platform_brokers=types.MappingProxyType({"kraken": platform})),
            broker_manager=types.SimpleNamespace(brokers=types.MappingProxyType({"kraken": user}),
                                                  get_primary_broker=lambda: user),
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
            multi_account_manager=types.SimpleNamespace(platform_brokers=types.MappingProxyType({"kraken": platform})),
            broker_manager=types.SimpleNamespace(brokers=types.MappingProxyType({"kraken": user}),
                                                 get_primary_broker=lambda: user),
            broker=user,
        )
        def unavailable_module(_):
            raise ImportError("fixture: v273 unavailable")
        env = extracted("runtime_heartbeat_live_venue_selection_v274_patch.py", ["_candidate_brokers"],
                        {"importlib": types.SimpleNamespace(import_module=unavailable_module), "Mapping": Mapping})
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

    def test_existing_fresh_marker_is_rejected_during_unfinished_attempt(self):
        marker = Path(self.directory.name) / "heartbeat_verified.flag"
        marker.write_text(json.dumps({"stage": "FILL_VERIFY", "verified_at_epoch": time.time() - 1,
                                      "source": "canonical_confirmed_fill", "proof_kind": "execution_probe"}))
        original_bytes = marker.read_bytes()
        env = extracted("trading_state_machine.py", ["_heartbeat_verification_status"], {
            "Path": Path, "json": json,
            "_heartbeat_marker_path": lambda: str(marker),
            "_heartbeat_min_required_stage": lambda: "FILL_VERIFY",
            "_heartbeat_verification_max_age_seconds": lambda: 1800.0,
            "_HEARTBEAT_STAGE_ORDER": {"AUTH_VERIFY": 1, "ORDER_VERIFY": 2, "FILL_VERIFY": 3},
        })
        with patch.dict(os.environ, {"NIJA_STARTUP_ATTEMPT_DB": str(self.path)}), patch.dict(
            sys.modules, {"bot": types.ModuleType("bot"), "bot.startup_verification_evidence": E}
        ):
            self.assertTrue(env["_heartbeat_verification_status"]()[0])
            E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
            for state in ["claimed", "entry_pending", "entry_filled", "exit_pending", "state_unknown"]:
                E.record_startup_attempt(self.identity, state, path=self.path)
                ok, reason, _ = env["_heartbeat_verification_status"]()
                self.assertFalse(ok)
                self.assertEqual(reason, "startup_attempt_unreconciled")
            self.assertEqual(marker.read_bytes(), original_bytes)

    def test_wakeup_cannot_trust_cached_ready_verifier_while_attempt_open(self):
        E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
        calls = []
        cached = types.SimpleNamespace(_heartbeat_verification_status=lambda: (calls.append(True) or True, "ready", {}))
        env = extracted("runtime_heartbeat_marker_convergence_v238_patch.py", ["_genuine_execution_marker_ready"],
                        {"importlib": types.SimpleNamespace(import_module=lambda _: cached)})
        with patch.dict(os.environ, {"NIJA_STARTUP_ATTEMPT_DB": str(self.path)}), patch.dict(
            sys.modules, {"bot": types.ModuleType("bot"), "bot.startup_verification_evidence": E}
        ):
            self.assertEqual(env["_genuine_execution_marker_ready"](), (False, "startup_attempt_unreconciled"))
        self.assertEqual(calls, [])

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

    def test_provenance_wrapper_checks_attempt_before_cached_original(self):
        calls = []
        module = types.SimpleNamespace(
            _heartbeat_verification_status=lambda: (calls.append(True) or True, "ready", {})
        )
        env = extracted("runtime_execution_capital_integrity_v169_patch.py", ["_patch_tsm_execution_provenance"], {
            "wraps": wraps, "_module_candidates": lambda *_: [module], "_PATCH_ATTR": "offline_fixture",
        })
        E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
        with patch.dict(os.environ, {"NIJA_STARTUP_ATTEMPT_DB": str(self.path)}), patch.dict(
            sys.modules, {"bot": types.ModuleType("bot"), "bot.startup_verification_evidence": E}
        ):
            self.assertTrue(env["_patch_tsm_execution_provenance"]())
            self.assertEqual(module._heartbeat_verification_status()[:2], (False, "startup_attempt_unreconciled"))
        self.assertEqual(calls, [])

    def test_provenance_wrapper_import_failure_is_fail_closed(self):
        module = types.SimpleNamespace(_heartbeat_verification_status=lambda: (True, "ready", {}))
        env = extracted("runtime_execution_capital_integrity_v169_patch.py", ["_patch_tsm_execution_provenance"], {
            "wraps": wraps, "_module_candidates": lambda *_: [module], "_PATCH_ATTR": "offline_fixture",
        })
        with patch.dict(sys.modules, {"bot.startup_verification_evidence": None}):
            self.assertTrue(env["_patch_tsm_execution_provenance"]())
            self.assertEqual(module._heartbeat_verification_status()[:2], (False, "startup_attempt_store_unavailable"))

    def test_startup_installer_keeps_attempt_guard_when_reapplied(self):
        installer_path = BOT.parent / "scripts" / "apply_execution_proof_startup_isolation_v339.py"
        spec = importlib.util.spec_from_file_location("_startup_installer_offline", installer_path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        source = (BOT / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text()
        patched = installer.patch_v238_text(source)
        self.assertEqual(installer.patch_v238_text(patched), patched)
        self.assertIn("v169_provenance_guard_not_ready", patched)
        self.assertIn('source != "heartbeat_trade"', patched)
        self.assertIn("startup_attempts_allow_execution_proof", patched)
        function = next(node for node in ast.parse(patched).body
                        if isinstance(node, ast.FunctionDef) and node.name == "_genuine_execution_marker_ready")
        calls = []
        namespace = {"os": os, "importlib": types.SimpleNamespace(
            import_module=lambda _: (calls.append(True) or types.SimpleNamespace())
        )}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(installer_path), "exec"), namespace)
        E.claim_startup_attempt(self.identity, "platform", "BTC-USD", path=self.path)
        with patch.dict(os.environ, {"NIJA_STARTUP_ATTEMPT_DB": str(self.path),
                                    "NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY": "1"}), patch.dict(
            sys.modules, {"bot": types.ModuleType("bot"), "bot.startup_verification_evidence": E}
        ):
            self.assertEqual(namespace["_genuine_execution_marker_ready"](), (False, "startup_attempt_unreconciled"))
        self.assertEqual(calls, [])

    def test_startup_installer_upgrades_both_legacy_consumer_forms(self):
        installer_path = BOT.parent / "scripts" / "apply_execution_proof_startup_isolation_v339.py"
        spec = importlib.util.spec_from_file_location("_startup_installer_legacy_offline", installer_path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        function = next(node for node in ast.parse(installer_path.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == "patch_v238_text")
        legacy_forms = [ast.literal_eval(node.value) for node in function.body[:2]]
        for source in legacy_forms:
            with self.subTest(already_hardened="v169_provenance_guard_not_ready" in source):
                patched = installer.patch_v238_text(source)
                self.assertEqual(installer.patch_v238_text(patched), patched)
                self.assertIn("startup_attempts_allow_execution_proof", patched)
                self.assertIn("v169_execution_provenance_missing", patched)


class FlowTests(unittest.TestCase):
    """Legacy startup heartbeat must never initiate a capital-bearing order."""

    def setUp(self):
        self.calls = []
        def forbidden(name):
            def _call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                raise AssertionError("legacy heartbeat must not call " + name)
            return _call
        self.forbidden = forbidden
        self.env = extracted(
            "trading_strategy.py",
            ["_execute_heartbeat_trade"],
            {
                "claim_startup_attempt": forbidden("claim_startup_attempt"),
                "submit_market_order_via_pipeline": forbidden("submit_market_order_via_pipeline"),
                "read_startup_broker_identity": forbidden("read_startup_broker_identity"),
            },
        )
        self.strategy = types.SimpleNamespace(
            _get_heartbeat_broker=forbidden("_get_heartbeat_broker"),
            _persist_heartbeat_marker=forbidden("_persist_heartbeat_marker"),
        )

    def test_unprotected_heartbeat_never_calls_broker_or_publishes_proof(self):
        for _ in range(2):
            self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
        self.assertEqual(self.calls, [])

    def test_legacy_entry_is_blocked_even_if_old_heartbeat_flags_are_set(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "attempts.db"
            with patch.dict(os.environ, {
                "NIJA_HEARTBEAT_ACCOUNT_FINGERPRINT": "a" * 64,
                "NIJA_HEARTBEAT_TRADE_ENABLED": "true",
                "NIJA_HEARTBEAT_TRADE_AMOUNT_USD": "5",
                "NIJA_STARTUP_ATTEMPT_DB": str(db),
            }):
                self.assertFalse(self.env["_execute_heartbeat_trade"](self.strategy))
            self.assertFalse(db.exists(), "blocked legacy entry must not claim persistent attempt")
        self.assertEqual(self.calls, [])

    def test_missing_strategy_adapter_is_still_fail_closed(self):
        self.assertFalse(self.env["_execute_heartbeat_trade"](None))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
