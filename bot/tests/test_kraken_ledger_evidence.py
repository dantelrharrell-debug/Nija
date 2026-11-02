"""Offline unittest coverage; fixtures stay under the repository, never /tmp."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import shutil
import sqlite3
import sys
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1]


def load_pure_module(name, filename):
    """Load stdlib-only sources without executing bot's package startup."""
    spec = importlib.util.spec_from_file_location(name, BOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ledger = load_pure_module("_tested_kraken_ledger_evidence", "kraken_ledger_evidence.py")
validator = load_pure_module("_tested_ledger_v452_validator", "pretrade_attestation_validation_v452.py")
KrakenLedgerDenied = ledger.KrakenLedgerDenied
ReviewedLedgerBinding = ledger.ReviewedLedgerBinding
_COLUMNS, _SCOPE_COLUMNS = ledger._COLUMNS, ledger._SCOPE_COLUMNS
make_kraken_ledger_evidence_provider = ledger.make_kraken_ledger_evidence_provider
PROOF_BY_SOURCE, REQUIRED, SOURCES = validator.PROOF_BY_SOURCE, validator.REQUIRED, validator.SOURCES
evaluate_pretrade_certificate = validator.evaluate_pretrade_certificate

NOW = 1_800_000_000.0
BUY = "OAAAAA-AAAAA-AAAAAA"
STOP = "OBBBBB-BBBBB-BBBBBB"
PROFIT = "OCCCCC-CCCCC-CCCCCC"
SELL = "ODDDDD-DDDDD-DDDDDD"
TID = "TAAAAA-AAAAA-AAAAAA"
SELL_TID = "TDDDDD-DDDDD-DDDDDD"
KEY = "synthetic-offline-api-key"
IBAN = "SYNTHETIC-OFFLINE-ACCOUNT"
KEY_HASH = hashlib.sha256(KEY.encode()).hexdigest()
ACCOUNT_HASH = hashlib.sha256(("kraken\0" + IBAN).encode()).hexdigest()
SCOPE = "user:alice:kraken"


def order(kind="limit", *, side="sell", volume="2", executed="0", trades=None):
    """Make unmodified-shaped Kraken order evidence."""
    return {
        "status": "open", "descr": {
            "pair": "XBTUSD", "type": side, "ordertype": kind, "price": "100",
        }, "vol": volume, "vol_exec": executed, "cost": "0", "fee": "0",
        "trades": [] if trades is None else trades,
    }


class Broker:
    """Existing nonce-owner stand-in; no network or order methods exist."""

    connected = True
    broker_type = "kraken"
    account_type = "user"
    user_id = "alice"

    def __init__(self):
        buy = order(side="buy", executed="2", trades=[TID])
        buy.update(status="closed", cost="200", fee="2")
        self.data = {
            "TradesHistory": {TID: {
                "ordertxid": BUY, "pair": "XXBTZUSD", "type": "buy",
                "vol": "2", "cost": "200", "fee": "2", "time": 100,
            }},
            "ClosedOrders": {BUY: buy},
            "Ledgers": {
                "deposit": {"asset": "ZUSD", "amount": "1000", "fee": "0",
                            "type": "deposit", "refid": "deposit-id"},
                "buy-base": {"asset": "XXBT", "amount": "2", "fee": "0",
                             "type": "trade", "refid": TID},
                "buy-quote": {"asset": "ZUSD", "amount": "-200", "fee": "2",
                              "type": "trade", "refid": TID},
            },
            "OpenOrders": {STOP: order("stop-loss"), PROFIT: order("take-profit")},
        }
        self.balance = {"XXBT": "2", "ZUSD": "798"}
        self.calls = []
        self.hook = None
        self.page_size = 50
        self.key = KEY
        self.iban = IBAN

    def _kraken_private_call(self, endpoint, params, *, category):
        self.calls.append((endpoint, copy.deepcopy(params), category))
        if self.hook:
            response = self.hook(endpoint, params)
            if response is not None:
                return response
        if endpoint == "GetApiKeyInfo":
            return {"error": [], "result": {
                "apiKey": self.key, "iban": self.iban, "validUntil": "0",
            }}
        if endpoint == "Balance":
            return {"error": [], "result": copy.deepcopy(self.balance)}
        field = {"TradesHistory": "trades", "ClosedOrders": "closed",
                 "Ledgers": "ledger", "OpenOrders": "open"}[endpoint]
        start = int(params.get("cursor", "0"))
        records = list(self.data[endpoint].items())
        stop = start + self.page_size
        rows = copy.deepcopy(dict(records[start:stop]))
        if endpoint in {"ClosedOrders", "OpenOrders"} and params.get("trades") not in (True, "true"):
            for row in rows.values():
                row.pop("trades", None)
        return {"error": [], "result": {
            field: rows,
            "cursor": {"next": str(stop) if stop < len(records) else None},
        }}


class KrakenLedgerEvidenceTests(unittest.TestCase):
    """Exercise concrete SQLite reads and real history pagination offline."""

    def setUp(self):
        self.root = Path(__file__).resolve().parent / (".ledger-fixture-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.path = self.root / "ledger.db"
        self.broker = Broker()
        self.scope = {
            "broker": "kraken", "account_scope": SCOPE,
            "api_key_sha256": KEY_HASH, "account_sha256": ACCOUNT_HASH,
        }
        with sqlite3.connect(self.path) as db:
            for table, fields in _COLUMNS.items():
                declarations = []
                for field in sorted(fields | _SCOPE_COLUMNS):
                    kind = "TEXT"
                    if field == "observed_at_epoch":
                        kind = "REAL"
                    elif field in {"schema_version", "history_from_genesis", "unresolved_submission_count"}:
                        kind = "INTEGER"
                    declarations.append(f'"{field}" {kind}')
                # The internal order_id is intentionally unrelated to the exchange.
                if table in {"trade_ledger", "pending_kraken_closes"}:
                    declarations.append("order_id TEXT")
                db.execute(f'CREATE TABLE "{table}" ({",".join(declarations)})')
        self.insert("ledger_evidence_state", {
            "schema_version": 1, "revision": "persisted-revision-1",
            "observed_at_epoch": NOW - 10, "history_from_genesis": 1,
            "unresolved_submission_count": 0,
        })
        self.insert("trade_ledger", {
            "user_id": "alice", "symbol": "BTC-USD", "side": "BUY", "action": "OPEN",
            "quantity": "2", "size_usd": "200", "fee": "2", "position_id": "internal-lot-1",
            "exchange_trade_id": TID, "exchange_order_id": BUY, "order_id": "internal-order-1",
        })
        self.insert("open_positions", {
            "user_id": "alice", "position_id": "internal-lot-1", "symbol": "BTC-USD",
            "side": "long", "quantity": "2", "status": "open",
            "stop_order_id": STOP, "take_profit_order_id": PROFIT,
        })
        for oid, kind in ((STOP, "stop-loss"), (PROFIT, "take-profit")):
            self.insert("ledger_open_orders", {
                "exchange_order_id": oid, "pair": "BTCUSD", "side": "sell",
                "ordertype": kind, "price": "100", "volume": "2", "executed": "0",
            })
        self.binding = ReviewedLedgerBinding(
            broker=self.broker, account=SCOPE, provider_id="external-reviewed-ledger",
            api_key_sha256=KEY_HASH, account_sha256=ACCOUNT_HASH,
            ledger_path=self.path, persistent_root=self.root,
            monitoring_category=object(),
        )

    def tearDown(self):
        shutil.rmtree(self.root)

    def insert(self, table, row):
        row = {**self.scope, **row}
        with sqlite3.connect(self.path) as db:
            db.execute(f'INSERT INTO "{table}" ({",".join(row)}) VALUES ({",".join("?" for _ in row)})',
                       list(row.values()))

    def update(self, table, field, value):
        with sqlite3.connect(self.path) as db:
            db.execute(f'UPDATE "{table}" SET "{field}"=?', (value,))

    def provider(self, **kwargs):
        return make_kraken_ledger_evidence_provider(
            self.binding, review_binding=lambda candidate: candidate is self.binding,
            clock=lambda: NOW, **kwargs,
        )

    def denied(self, reason=None):
        with self.assertRaises(KrakenLedgerDenied) as result:
            self.provider()()
        if reason:
            self.assertEqual(str(result.exception), reason)
        self.assertNotIn(KEY, str(result.exception))
        self.assertNotIn(IBAN, str(result.exception))
        return str(result.exception)

    def partial_close(self, *, terminal=False):
        self.insert("trade_ledger", {
            "user_id": "alice", "symbol": "BTC-USD", "side": "SELL", "action": "CLOSE",
            "quantity": "1", "size_usd": "100", "fee": "1", "position_id": "internal-lot-1",
            "exchange_trade_id": SELL_TID, "exchange_order_id": SELL, "order_id": "internal-close",
        })
        self.update("open_positions", "quantity", "1")
        self.insert("pending_kraken_closes", {
            "user_id": "alice", "exchange_order_id": SELL, "position_id": "internal-lot-1",
            "quantity": "1" if terminal else "2", "executed": "1", "fee": "1",
            "state": "reconciled" if terminal else "pending",
            "symbol": "BTC-USD", "side": "sell", "order_id": "internal-close",
        })
        sell = order(volume="1" if terminal else "2", executed="1", trades=[SELL_TID])
        sell.update(cost="100", fee="1")
        if terminal:
            sell["status"] = "closed"
            self.broker.data["ClosedOrders"][SELL] = sell
        else:
            self.broker.data["OpenOrders"][SELL] = sell
            self.insert("ledger_open_orders", {
                "exchange_order_id": SELL, "pair": "BTCUSD", "side": "sell", "ordertype": "limit",
                "price": "100", "volume": "2", "executed": "1",
            })
        self.broker.data["TradesHistory"][SELL_TID] = {
            "ordertxid": SELL, "pair": "XBTUSD", "type": "sell", "vol": "1",
            "cost": "100", "fee": "1",
        }
        self.broker.data["Ledgers"].update({
            "sell-base": {"asset": "XXBT", "amount": "-1", "fee": "0",
                          "type": "trade", "refid": SELL_TID},
            "sell-quote": {"asset": "ZUSD", "amount": "100", "fee": "1",
                           "type": "trade", "refid": SELL_TID},
        })
        self.broker.balance = {"XXBT": "1", "ZUSD": "897"}

    def test_complete_real_reads_and_v452_shape_without_mutation(self):
        before = self.path.read_bytes()
        provider = self.provider()
        self.assertFalse(self.broker.calls)
        evidence = provider()
        self.assertTrue(evidence["verified"])
        self.assertEqual(evidence["account"], SCOPE)
        self.assertFalse(evidence["authorizes_orders"])
        self.assertTrue(evidence["read_only"])
        self.assertEqual(evidence["source"], "independent_ledger")
        self.assertEqual(evidence["observed_at_epoch"], NOW - 10)
        self.assertFalse(evidence["atomic_broker_snapshot_verified"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertNotEqual(evidence["evidence_id"], provider()["evidence_id"])
        self.assertEqual({endpoint for endpoint, _, _ in self.broker.calls}, {
            "GetApiKeyInfo", "Balance", "TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders",
        })
        self.assertTrue(all(category is self.binding.monitoring_category
                            for _, _, category in self.broker.calls))
        self.assertNotIn(KEY, repr(evidence))
        observations, trusted = {}, {}
        for field in REQUIRED:
            source = SOURCES[field]
            pid = "external-" + field
            trusted[field] = pid
            observations[field] = {
                "account": SCOPE, "verified": True, "read_only": True, "scope_verified": True,
                "source": source, "provider_id": pid, "evidence_id": field,
                "observed_at_epoch": NOW, "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, PROOF_BY_SOURCE[source]: True,
                    "complete_pagination_verified": True,
                },
            }
        observations["position_ledger_reconciliation"] = evidence
        trusted["position_ledger_reconciliation"] = self.binding.provider_id
        self.assertTrue(evaluate_pretrade_certificate(
            observations, account=SCOPE, trusted_provider_ids=trusted, now_epoch=NOW,
        )["certified"])

    def test_review_is_mandatory_not_a_string_or_boolean(self):
        for review in (True, "reviewed", lambda _: False, lambda _: 1):
            with self.subTest(review=type(review).__name__):
                with self.assertRaises(KrakenLedgerDenied):
                    make_kraken_ledger_evidence_provider(self.binding, review_binding=review)
        cloned = replace(self.binding)
        with self.assertRaises(KrakenLedgerDenied):
            make_kraken_ledger_evidence_provider(cloned, review_binding=lambda item: item is self.binding)
        self.assertFalse(self.broker.calls)

    def test_review_revocation(self):
        approved = [True]
        provider = make_kraken_ledger_evidence_provider(
            self.binding, review_binding=lambda _: approved[0], clock=lambda: NOW,
        )
        approved[0] = False
        with self.assertRaisesRegex(KrakenLedgerDenied, "reviewed_binding_revoked"):
            provider()
        self.assertFalse(self.broker.calls)

    def test_missing_database_does_not_create(self):
        self.path.unlink()
        self.denied()
        self.assertFalse(self.path.exists())

    def test_nonpersistent_root_rejected(self):
        elsewhere = self.root / "not-the-ledger-root"
        elsewhere.mkdir()
        self.binding = replace(self.binding, persistent_root=elsewhere)
        self.denied("persistent_ledger_path_unverified")
        self.assertFalse(self.broker.calls)

    def test_corrupt_database_denied_without_mutation(self):
        self.path.write_bytes(b"not-a-database")
        self.denied("ledger_evidence_unavailable")
        self.assertEqual(self.path.read_bytes(), b"not-a-database")

    def test_symlink_database_and_nonpersistent_path_rejected(self):
        target = self.root / "real.db"
        self.path.rename(target)
        self.path.symlink_to(target)
        self.denied("persistent_ledger_path_unverified")
        self.assertFalse(self.broker.calls)

    def test_legacy_schema_explicitly_denies_missing_broker_provenance(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE trade_ledger")
            db.execute("CREATE TABLE trade_ledger (user_id TEXT, order_id TEXT, quantity REAL)")
        self.denied("ledger_broker_account_api_provenance_missing")
        self.assertFalse(self.broker.calls)

    def test_missing_contract_table_denied(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE pending_kraken_closes")
        self.denied("ledger_schema_contract_missing")

    def test_inert_offline_schema_matches_reader_and_does_not_certify_empty_database(self):
        separate_path = self.root / "offline-certification.db"
        original = self.path.read_bytes()
        statements = ledger.offline_ledger_schema_sql()
        self.assertIsInstance(statements, tuple)
        self.assertEqual(len(statements), len(_COLUMNS))
        self.assertFalse(separate_path.exists())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.broker.calls)
        with sqlite3.connect(separate_path) as db:
            for statement in statements:
                self.assertTrue(statement.startswith("CREATE TABLE "))
                self.assertNotIn("DEFAULT", statement)
                db.execute(statement)
            for table, columns in _COLUMNS.items():
                actual = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                self.assertTrue(columns | _SCOPE_COLUMNS <= actual)
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0)
        self.binding = replace(self.binding, ledger_path=separate_path)
        self.denied("ledger_snapshot_state_missing_or_duplicate")
        self.assertFalse(self.broker.calls)
        with sqlite3.connect(separate_path) as db:
            row = {
                **self.scope, "schema_version": 1, "revision": "not-genesis-verified",
                "observed_at_epoch": NOW, "history_from_genesis": 0, "unresolved_submission_count": 0,
            }
            db.execute(
                f'INSERT INTO ledger_evidence_state ({",".join(row)}) VALUES ({",".join("?" for _ in row)})',
                list(row.values()),
            )
        self.denied("ledger_snapshot_state_unverified")
        self.assertFalse(self.broker.calls)
        self.assertEqual(self.path.read_bytes(), original)

    def test_offline_schema_requires_explicit_provenance_and_state_fields(self):
        with sqlite3.connect(":memory:") as db:
            for statement in ledger.offline_ledger_schema_sql():
                db.execute(statement)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO ledger_evidence_state DEFAULT VALUES")
            for table in _COLUMNS:
                provenance = {row[1]: row for row in db.execute(f'PRAGMA table_info("{table}")')}
                for column in _SCOPE_COLUMNS:
                    self.assertEqual(provenance[column][3], 1)
                    self.assertIsNone(provenance[column][4])

    def test_view_cannot_impersonate_persisted_table(self):
        with sqlite3.connect(self.path) as db:
            db.execute("ALTER TABLE ledger_open_orders RENAME TO saved_orders")
            db.execute("CREATE VIEW ledger_open_orders AS SELECT * FROM saved_orders")
        self.denied("ledger_schema_contract_missing")

    def test_api_fingerprint_account_and_broker_conflicts(self):
        for column, value in (("api_key_sha256", "0" * 64), ("account_sha256", "1" * 64),
                              ("broker", "coinbase")):
            with self.subTest(column=column):
                self.update("trade_ledger", column, value)
                self.denied("ledger_scope_fingerprint_conflict")
                self.update("trade_ledger", column, self.scope[column])

    def test_null_provenance_is_not_silently_filtered(self):
        self.update("trade_ledger", "broker", None)
        self.denied("ledger_row_provenance_missing")

    def test_wrong_user_assignment_denied(self):
        for table in ("trade_ledger", "open_positions"):
            self.update(table, "user_id", "bob")
            self.denied("ledger_user_assignment_conflict")
            self.update(table, "user_id", "alice")

    def test_other_scope_not_inferred_from_matching_user(self):
        self.update("trade_ledger", "account_scope", "user:bob:kraken")
        self.denied("ledger_broker_fill_set_mismatch")

    def test_other_account_rows_remain_isolated(self):
        self.insert("trade_ledger", {
            "user_id": "bob", "account_scope": "user:bob:kraken", "symbol": "BTC-USD",
            "side": "BUY", "action": "OPEN", "quantity": "999", "size_usd": "999",
            "fee": "0", "position_id": "other", "exchange_trade_id": "other",
            "exchange_order_id": "other",
        })
        self.assertTrue(self.provider()()["verified"])

    def test_platform_scope_requires_platform_assignment(self):
        with sqlite3.connect(self.path) as db:
            for table in _COLUMNS:
                db.execute(f'UPDATE "{table}" SET account_scope=?', ("platform:kraken",))
                if "user_id" in _COLUMNS[table]:
                    db.execute(f'UPDATE "{table}" SET user_id=?', ("platform",))
        self.broker.account_type, self.broker.user_id = "platform", None
        self.binding = replace(self.binding, account="platform:kraken")
        self.assertEqual(self.provider()()["account"], "platform:kraken")

    def test_internal_order_identifier_is_never_used_as_exchange_id(self):
        self.update("trade_ledger", "exchange_order_id", "internal-order-1")
        self.denied("exchange_order_id_required")

    def test_prices_do_not_substitute_for_protective_order_ids(self):
        self.update("open_positions", "stop_order_id", "99.5")
        self.denied("exchange_order_id_required")

    def test_stale_future_and_invalid_source_timestamps(self):
        for stamp in (NOW - 60.001, NOW + 1, "not-a-clock", None, 0):
            with self.subTest(stamp=stamp):
                self.update("ledger_evidence_state", "observed_at_epoch", stamp)
                self.denied("source_timestamp_invalid_or_stale")
                self.assertFalse(self.broker.calls)

    def test_exact_freshness_boundary(self):
        self.update("ledger_evidence_state", "observed_at_epoch", NOW - 60)
        self.assertEqual(self.provider()()["observed_at_epoch"], NOW - 60)

    def test_missing_genesis_and_unresolved_submissions(self):
        for field, value in (("history_from_genesis", 0), ("unresolved_submission_count", 1),
                             ("schema_version", 2), ("revision", "")):
            self.update("ledger_evidence_state", field, value)
            self.denied("ledger_snapshot_state_unverified")
            self.update("ledger_evidence_state", field, {
                "history_from_genesis": 1, "unresolved_submission_count": 0,
                "schema_version": 1, "revision": "persisted-revision-1",
            }[field])

    def test_duplicate_snapshot_state_denied(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO ledger_evidence_state SELECT * FROM ledger_evidence_state")
        self.denied("ledger_snapshot_state_missing_or_duplicate")

    def test_snapshot_row_budget_enforced(self):
        with patch.object(ledger, "MAX_ROWS", 1):
            self.denied("ledger_row_budget_exceeded")
        self.assertFalse(self.broker.calls)

    def test_actual_authenticated_identity_is_pinned(self):
        self.broker.key = "wrong-key"
        self.denied("authenticated_identity_pin_mismatch")
        self.broker.key = KEY
        self.broker.iban = "OTHER-ACCOUNT"
        self.denied("authenticated_identity_pin_mismatch")

    def test_broker_scope_changes_fail(self):
        def hook(endpoint, _params):
            if endpoint == "TradesHistory":
                self.broker.user_id = "bob"
        self.broker.hook = hook
        self.denied("broker_scope_or_transport_changed")

    def test_existing_transport_replacement_denied(self):
        provider = self.provider()
        self.broker._kraken_private_call = lambda *args, **kwargs: {"error": [], "result": {}}
        with self.assertRaisesRegex(KrakenLedgerDenied, "broker_scope_or_transport_changed"):
            provider()

    def test_nonce_mutation_does_not_pollute_cursor_or_next_read(self):
        self.broker.page_size = 1
        def hook(_endpoint, params):
            self.assertNotIn("nonce", params)
            params["nonce"] = 123
        self.broker.hook = hook
        self.assertTrue(self.provider()()["verified"])

    def test_direct_form_wire_flags_match_existing_kraken_transport(self):
        self.broker._gateway_url = ""
        self.assertTrue(self.provider()()["verified"])
        for endpoint, params, _category in self.broker.calls:
            if endpoint not in {"Balance", "GetApiKeyInfo"}:
                self.assertEqual(params["with_cursor"], "true")
            if endpoint in {"ClosedOrders", "OpenOrders"}:
                self.assertEqual(params["trades"], "true")

    def test_gateway_keeps_boolean_flags_and_orders_require_explicit_trade_links(self):
        self.broker._gateway_url = "https://offline.invalid"
        self.broker.page_size = 1
        self.partial_close(terminal=True)
        without = self.broker._kraken_private_call(
            "ClosedOrders", {"with_cursor": True}, category=self.binding.monitoring_category,
        )
        self.assertNotIn("trades", next(iter(without["result"]["closed"].values())))
        self.broker.calls.clear()
        self.assertTrue(self.provider()()["verified"])
        for endpoint, params, _category in self.broker.calls:
            if endpoint not in {"Balance", "GetApiKeyInfo"}:
                self.assertIs(params["with_cursor"], True)
            if endpoint in {"ClosedOrders", "OpenOrders"}:
                self.assertIs(params["trades"], True)
            if endpoint == "OpenOrders":
                self.assertEqual(params["limit"], 50)
            else:
                self.assertNotIn("limit", params)

    def test_expired_key_is_not_authenticated_current_identity(self):
        def hook(endpoint, _params):
            if endpoint == "GetApiKeyInfo":
                return {"error": [], "result": {
                    "apiKey": KEY, "iban": IBAN, "validUntil": str(int(NOW)),
                }}
        self.broker.hook = hook
        self.denied("authenticated_key_expired_or_invalid")

    def test_authenticated_identity_changes_after_history(self):
        def hook(endpoint, _params):
            if endpoint == "OpenOrders":
                self.broker.key = "changed-key"
        self.broker.hook = hook
        self.denied("authenticated_identity_pin_mismatch")

    def test_complete_cursor_pagination_for_every_history_endpoint(self):
        self.broker.page_size = 1
        self.partial_close()
        self.assertTrue(self.provider()()["verified"])
        for endpoint in ("TradesHistory", "ClosedOrders", "Ledgers", "OpenOrders"):
            if len(self.broker.data[endpoint]) > 1:
                self.assertTrue(any(ep == endpoint and "cursor" in params
                                    for ep, params, _ in self.broker.calls))

    def test_page_budget_exhaustion_denied(self):
        self.broker.page_size = 1
        with self.assertRaises(KrakenLedgerDenied):
            self.provider(max_pages=1)()

    def test_repeated_cursor_duplicate_ids_and_incomplete_cursor_denied(self):
        for mode in ("repeat", "duplicate", "missing", "unknown", "empty"):
            with self.subTest(mode=mode):
                def hook(endpoint, params):
                    if endpoint != "TradesHistory":
                        return None
                    if mode == "missing":
                        return {"error": [], "result": {"trades": {}}}
                    if mode == "unknown":
                        return {"error": [], "result": {"trades": {}, "cursor": {"offset": 1}}}
                    if mode == "empty":
                        return {"error": [], "result": {"trades": {}, "cursor": {"next": "1"}}}
                    row = self.broker.data["TradesHistory"][TID]
                    tid = "T-first" if "cursor" not in params else ("T-second" if mode == "repeat" else "T-first")
                    return {"error": [], "result": {
                        "trades": {tid: row}, "cursor": {"next": "1" if mode == "repeat" else (
                            "1" if "cursor" not in params else None)},
                    }}
                self.broker.hook = hook
                self.denied("history_record_invalid_or_duplicate" if mode == "duplicate"
                            else "history_pagination_invalid")

    def test_changing_history_balances_and_orders_denied(self):
        for target in ("TradesHistory", "Balance", "OpenOrders"):
            with self.subTest(target=target):
                counter = [0]
                original_data, original_balance = copy.deepcopy(self.broker.data), copy.deepcopy(self.broker.balance)
                def hook(endpoint, _params):
                    if endpoint == target:
                        counter[0] += 1
                        if counter[0] == 2:
                            if target == "Balance":
                                self.broker.balance["ZUSD"] = "797"
                            elif target == "OpenOrders":
                                self.broker.data[target][STOP]["descr"]["price"] = "99"
                            else:
                                self.broker.data[target][TID]["cost"] = "201"
                self.broker.hook = hook
                self.denied({
                    "TradesHistory": "authenticated_history_changed",
                    "Balance": "authenticated_balances_changed",
                    "OpenOrders": "authenticated_open_orders_changed",
                }[target])
                self.broker.data, self.broker.balance = original_data, original_balance

    def test_secret_transport_errors_and_malformed_payload_are_redacted(self):
        for payload in (None, {"error": [KEY + IBAN]}, {"error": [], "result": "secret"}):
            def hook(endpoint, _params):
                if endpoint == "TradesHistory":
                    if payload is None:
                        raise RuntimeError(KEY + IBAN)
                    return payload
            self.broker.hook = hook
            self.denied("ledger_evidence_unavailable" if payload is None else "authenticated_response_invalid")

    def test_concurrent_database_change_even_restored_values_denied(self):
        changed = [False]
        def hook(endpoint, _params):
            if endpoint == "TradesHistory" and not changed[0]:
                changed[0] = True
                self.update("trade_ledger", "fee", "3")
                self.update("trade_ledger", "fee", "2")
        self.broker.hook = hook
        self.denied("concurrent_ledger_change")

    def test_concurrent_database_replacement_denied(self):
        replaced = [False]
        def hook(endpoint, _params):
            if endpoint == "TradesHistory" and not replaced[0]:
                replaced[0] = True
                sibling = self.root / "replacement.db"
                sibling.write_bytes(self.path.read_bytes())
                sibling.replace(self.path)
        self.broker.hook = hook
        self.denied("concurrent_ledger_change")

    def test_fill_quantity_fees_cost_side_and_pair_must_match(self):
        for field, value in (("quantity", "1.99"), ("fee", "1.99"), ("size_usd", "199.99"),
                             ("symbol", "ETH-USD")):
            original = {"quantity": "2", "fee": "2", "size_usd": "200", "symbol": "BTC-USD"}[field]
            self.update("trade_ledger", field, value)
            self.denied("ledger_broker_fill_terms_mismatch")
            self.update("trade_ledger", field, original)
        self.update("trade_ledger", "side", "SELL")
        self.denied("ledger_side_action_invalid")

    def test_duplicate_fill_denied(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO trade_ledger SELECT * FROM trade_ledger")
        self.denied("fill_or_position_identity_invalid")

    def test_partial_and_reconciled_closes_have_exact_persistent_terms(self):
        self.partial_close()
        evidence = self.provider()()
        self.assertEqual(evidence["positions"]["internal-lot-1"]["quantity"], "1")
        self.assertTrue(evidence["pending_closes_reconciled"])
        self.update("pending_kraken_closes", "fee", "0.5")
        self.denied("pending_close_terms_mismatch")

    def test_reconciled_terminal_close(self):
        self.partial_close(terminal=True)
        self.assertTrue(self.provider()()["verified"])

    def test_pending_terminal_close_not_silently_repaired(self):
        self.partial_close(terminal=True)
        self.update("pending_kraken_closes", "state", "pending")
        self.denied("pending_close_state_unresolved")

    def test_pending_close_wrong_lot_denied(self):
        self.partial_close()
        self.update("pending_kraken_closes", "position_id", "unknown-lot")
        self.denied("pending_close_identity_invalid")

    def test_order_fill_links_and_totals(self):
        self.broker.data["ClosedOrders"][BUY]["trades"] = []
        self.denied("broker_order_fill_links_mismatch")
        self.broker.data["ClosedOrders"][BUY]["trades"] = [TID]
        self.broker.data["ClosedOrders"][BUY]["fee"] = "3"
        self.denied("broker_order_fill_totals_mismatch")

    def test_margin_fills_and_orders_are_never_spot_certified(self):
        self.broker.data["TradesHistory"][TID]["margin"] = "50"
        self.denied("margin_history_unsupported")
        self.broker.data["TradesHistory"][TID]["margin"] = "0"
        self.broker.data["ClosedOrders"][BUY]["descr"]["leverage"] = "2"
        self.denied("margin_history_unsupported")

    def test_independent_open_order_intents_must_match(self):
        self.update("ledger_open_orders", "price", "99")
        self.denied("ledger_broker_open_orders_mismatch")

    def test_protective_coverage_and_id_reuse(self):
        self.update("open_positions", "take_profit_order_id", STOP)
        self.denied("protective_id_missing_or_reused")
        self.update("open_positions", "take_profit_order_id", PROFIT)
        self.broker.data["OpenOrders"][STOP]["descr"]["ordertype"] = "limit"
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE ledger_open_orders SET ordertype='limit' WHERE exchange_order_id=?", (STOP,))
        self.denied("protective_order_coverage_mismatch")

    def test_absent_exchange_protective_order(self):
        self.update("open_positions", "stop_order_id", SELL)
        self.denied("protective_order_not_open")

    def test_position_quantities_and_unknown_inventory_denied(self):
        self.update("open_positions", "quantity", "1")
        self.denied("ledger_position_fill_quantity_mismatch")
        self.update("open_positions", "quantity", "2")
        self.broker.data["Ledgers"]["base-deposit"] = {
            "asset": "XXBT", "amount": "1", "fee": "0", "type": "deposit", "refid": "external",
        }
        self.broker.balance["XXBT"] = "3"
        self.denied("position_broker_balance_mismatch")

    def test_exchange_ledger_fees_and_balances_are_reconciled(self):
        self.broker.data["Ledgers"]["buy-quote"]["fee"] = "1"
        self.denied("exchange_ledger_fill_amounts_or_fees_mismatch")
        self.broker.data["Ledgers"]["buy-quote"]["fee"] = "2"
        self.broker.balance["ZUSD"] = "799"
        self.denied("exchange_ledger_balance_mismatch")

    def test_exchange_cash_ledger_missing_fill_links_is_denied(self):
        self.broker.data["Ledgers"]["buy-base"]["refid"] = "not-a-known-trade"
        self.denied("exchange_ledger_trade_link_missing")

    def test_invalid_decimal_and_nonfinite_values_denied(self):
        for value in ("NaN", "Infinity", "-1", "1e9999", "x" * 129):
            self.update("trade_ledger", "quantity", value)
            self.denied("amount_invalid")

    def test_subdecimal_precision_disagreement_not_rounded_away(self):
        self.update("trade_ledger", "fee", "2.000000000000000000000000000001")
        self.denied("ledger_broker_fill_terms_mismatch")

    def test_unmatched_and_duplicate_alias_balances_denied(self):
        self.broker.balance["BTC"] = "2"
        self.denied("duplicate_balance_asset_alias")

    def test_flat_complete_account_is_valid_not_fake_missing_history(self):
        with sqlite3.connect(self.path) as db:
            for table in _COLUMNS:
                if table != "ledger_evidence_state":
                    db.execute(f'DELETE FROM "{table}"')
        self.broker.data = {endpoint: {} for endpoint in self.broker.data}
        self.broker.balance = {}
        self.assertEqual(self.provider()()["positions"], {})

    def test_unknown_pair_and_assets_fail_explicitly(self):
        self.update("trade_ledger", "symbol", "SOL-USD")
        self.denied("unsupported_spot_pair")
        self.update("trade_ledger", "symbol", "BTC-USD")
        self.broker.balance["UNKNOWN"] = "0"
        self.denied("unsupported_balance_asset")

    def test_full_collection_must_finish_within_sixty_seconds(self):
        now = [NOW]
        def hook(endpoint, _params):
            if endpoint == "OpenOrders":
                now[0] = NOW + 61
        self.broker.hook = hook
        provider = make_kraken_ledger_evidence_provider(
            self.binding, review_binding=lambda item: item is self.binding, clock=lambda: now[0],
        )
        with self.assertRaises(KrakenLedgerDenied):
            provider()

    def test_module_import_does_not_call_broker_or_register(self):
        before = set(sys.modules)
        module = load_pure_module("_reimported_pure_ledger", "kraken_ledger_evidence.py")
        self.assertFalse(self.broker.calls)
        self.assertFalse(any(name == "bot" or name.startswith("bot.") for name in set(sys.modules) - before))
        self.assertEqual(module.__all__, [
            "KrakenLedgerDenied", "ReviewedLedgerBinding", "make_kraken_ledger_evidence_provider",
            "offline_ledger_schema_sql",
        ])


if __name__ == "__main__":
    unittest.main()
