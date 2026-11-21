"""Offline regression for Kraken protective-exit readback v485."""
import copy
import hashlib
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "bot")]
    sys.modules["bot"] = pkg

from bot.kraken_protective_exit_readback_v485 import (
    KrakenProtectionDenied, make_kraken_protective_exit_provider, rehearse_cash_only_baseline,
)

KEY = "synthetic-key"
IBAN = "AA00 TEST"
KEY_PIN = hashlib.sha256(KEY.encode()).hexdigest()
IBAN_PIN = hashlib.sha256(("kraken" + chr(0) + IBAN).encode()).hexdigest()
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
        self.balances = {"ZUSD": {"balance": "100", "hold_trade": "0"},
                         "XXBT": {"balance": "0", "hold_trade": "0"}}
        self.margin_positions = {}

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
            assert params == {"with_cursor": "true", "limit": 50, "trades": "true"}
            return {"error": [], "result": {
                "open": copy.deepcopy(self.orders), "cursor": {},
            }}
        if method in {"BalanceEx", "OpenPositions"}:
            assert params == {}
            value = self.balances if method == "BalanceEx" else self.margin_positions
            return {"error": [], "result": copy.deepcopy(value)}
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


class FlatLedger(Ledger):
    """Synthetic complete proof; never an approval or production data source."""

    def __init__(self):
        super().__init__()
        self.positions = {}

    def __call__(self):
        row = super().__call__()
        return {
            **row, "verified": True, "read_only": True, "scope_verified": True,
            "authorizes_orders": False, "evidence_id": "offline-read-" + str(self.calls),
            "pending_closes_reconciled": True, "outstanding_intents_reconciled": True,
            "unresolved_submission_count": 0, "orders": {},
            "provenance": {
                "account_scope_verified": True, "collector_identity_verified": True,
                "snapshot_complete": True, "ledger_snapshot_verified": True,
                "complete_pagination_verified": True,
            },
        }


def build(broker, ledger, *, clock=lambda: 1001.0):
    return make_kraken_protective_exit_provider(
        broker, account_scope="platform:kraken",
        approved_api_key_sha256=KEY_PIN,
        approved_iban_sha256=IBAN_PIN,
        reviewed_provider_id="broker-protection",
        reviewed_ledger_provider_id="independent-ledger",
        independent_positions=ledger, monitoring_category=CATEGORY,
        clock=clock,
    )


class TestProtection(unittest.TestCase):
    def test_cash_only_rehearsal_does_not_certify_history_or_ignore_margin(self):
        broker = Broker()
        broker.orders.clear()
        def observe():
            return rehearse_cash_only_baseline(
                broker, account_scope="platform:kraken", approved_api_key_sha256=KEY_PIN,
                approved_iban_sha256=IBAN_PIN, reviewed_provider_id="cash-only-rehearsal",
                monitoring_category=CATEGORY, clock=lambda: 1001.0,
            )
        report = observe()
        self.assertTrue(report["default_wallet_cash_only_observed"])
        self.assertFalse(report["historical_attribution_verified"])
        self.assertFalse(report["authorizes_orders"])
        self.assertEqual(broker.calls.count("OpenPositions"), 2)
        broker.margin_positions = {"synthetic": {}}
        with self.assertRaisesRegex(KrakenProtectionDenied, "flat_margin_exposure_present"):
            observe()

    def test_opening_cash_compares_both_reads_without_certification(self):
        broker = Broker()
        broker.orders.clear()

        def compare(value):
            return rehearse_cash_only_baseline(
                broker, account_scope="platform:kraken", approved_api_key_sha256=KEY_PIN,
                approved_iban_sha256=IBAN_PIN, reviewed_provider_id="cash-only-rehearsal",
                monitoring_category=CATEGORY, clock=lambda: 1001.0, expected_usd=value,
            )

        self.assertFalse(compare(None)["supplied_usd_matched"])
        report = compare("100.000")
        self.assertTrue(report["supplied_usd_matched"])
        self.assertFalse(report["collector_install_allowed"])
        self.assertFalse(report["authorizes_orders"])
        with self.assertRaisesRegex(KrakenProtectionDenied, "opening_cash_mismatch"):
            compare("100.000000000000000001")
        with self.assertRaises(KrakenProtectionDenied):
            compare(100.0)
        broker.balances.clear()
        with self.assertRaisesRegex(KrakenProtectionDenied, "opening_cash_mismatch"):
            compare("0")

    def test_verified_protection_read_only(self):
        broker, ledger = Broker(), Ledger()
        provider = build(broker, ledger)
        self.assertEqual(broker.calls, [])
        result = provider()
        self.assertTrue(result["verified"])
        self.assertFalse(result["authorizes_orders"])
        self.assertEqual(broker.calls.count("OpenOrders"), 2)
        self.assertEqual(ledger.calls, 2)
        self.assertNotIn("BalanceEx", broker.calls)
        self.assertNotIn("OpenPositions", broker.calls)

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

    def test_wrong_exit_direction_denied(self):
        broker, ledger = Broker(), Ledger()
        broker.orders[STOP]["descr"]["type"] = "buy"
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()

    def test_changed_ledger_snapshot_denied(self):
        broker, ledger = Broker(), Ledger()
        original = ledger.__call__
        def changed():
            row = original()
            if ledger.calls == 2:
                row["snapshot_id"] = "snapshot-2"
            return row
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, changed)()

    def test_stale_ledger_denied(self):
        broker, ledger = Broker(), Ledger()
        original = ledger.__call__
        def stale():
            row = original()
            row["observed_at_epoch"] = 900.0
            return row
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, stale)()

    def test_non_exchange_order_id_denied(self):
        broker, ledger = Broker(), Ledger()
        ledger.positions["lot-1"]["stop_order_id"] = "internal-stop-ref"
        with self.assertRaises(KrakenProtectionDenied):
            build(broker, ledger)()
        self.assertNotIn("OpenOrders", broker.calls)

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


class TestVerifiedFlatProtection(unittest.TestCase):
    """Offline source-contract tests; no broker connection or order submission."""

    def setUp(self):
        self.broker, self.ledger = Broker(), FlatLedger()
        self.broker.orders = {}

    def changed_ledger(self, change):
        def observe():
            row = self.ledger()
            change(row)
            return row
        return observe

    def test_complete_flat_proof_needs_repeated_orders_spot_and_margin_reads(self):
        provider = build(self.broker, self.ledger)
        self.assertEqual(self.broker.calls, [])
        result = provider()
        self.assertTrue(result["verified"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["authorizes_orders"])
        self.assertEqual(result["protection_status"], "verified_flat_no_exits_required")
        self.assertEqual(result["observed_at_epoch"], 1000.0)
        self.assertEqual(result["expires_at_epoch"], 1060.0)
        self.assertEqual(self.broker.calls, [
            "GetApiKeyInfo", "OpenOrders", "BalanceEx", "OpenPositions",
            "OpenOrders", "BalanceEx", "OpenPositions", "GetApiKeyInfo",
        ])
        self.assertEqual(self.ledger.calls, 2)
        self.assertNotIn("balances", result)
        self.assertNotIn("ZUSD", str(result))

    def test_zero_funds_and_zero_credit_fields_are_explicitly_supported(self):
        for balances in ({}, {"USD": {"balance": "0", "hold_trade": "0", "credit": "0", "credit_used": "0"}}):
            with self.subTest(balances=balances):
                self.broker.balances = balances
                result = build(self.broker, self.ledger)()
                self.assertEqual(result["protection_status"], "verified_flat_no_exits_required")
                self.assertFalse(result["authorizes_orders"])

    def test_every_required_flat_ledger_field_must_exist(self):
        for field in (
            "account", "provider_id", "source", "snapshot_complete", "fills_reconciled",
            "positions_reconciled", "snapshot_id", "observed_at_epoch", "positions",
            "verified", "read_only", "scope_verified", "authorizes_orders", "evidence_id",
            "pending_closes_reconciled", "outstanding_intents_reconciled",
            "unresolved_submission_count", "orders", "provenance",
        ):
            with self.subTest(field=field), self.assertRaises(KrakenProtectionDenied):
                build(self.broker, self.changed_ledger(lambda row: row.pop(field)))()
        self.assertNotIn("BalanceEx", self.broker.calls)

    def test_flat_proof_rejects_wrong_scope_unresolved_intents_and_false_flags(self):
        for field, value in (
            ("account", "user:other:kraken"), ("provider_id", "unreviewed-source"),
            ("source", "authenticated_broker"), ("verified", 1), ("read_only", False),
            ("scope_verified", None), ("authorizes_orders", True), ("evidence_id", " "),
            ("pending_closes_reconciled", False), ("outstanding_intents_reconciled", 1),
            ("unresolved_submission_count", True), ("unresolved_submission_count", 1),
            ("orders", []), ("orders", {STOP: {}}), ("positions", []),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(KrakenProtectionDenied):
                build(self.broker, self.changed_ledger(lambda row: row.update({field: value})))()

    def test_every_flat_provenance_flag_must_be_literal_true(self):
        for field in ("account_scope_verified", "collector_identity_verified", "snapshot_complete",
                      "ledger_snapshot_verified", "complete_pagination_verified"):
            for value in (False, None, 1, "true"):
                with self.subTest(field=field, value=value), self.assertRaises(KrakenProtectionDenied):
                    build(self.broker, self.changed_ledger(
                        lambda row: row["provenance"].update({field: value}),
                    ))()

    def test_shorter_expiry_is_preserved_and_invalid_or_stale_time_denies(self):
        result = build(self.broker, self.changed_ledger(lambda row: row.update(expires_at_epoch=1002.0)))()
        self.assertEqual(result["expires_at_epoch"], 1002.0)
        self.assertEqual(result["observed_at_epoch"], 1000.0)
        for field, value in (
            ("observed_at_epoch", 0), ("observed_at_epoch", 941.0),
            ("observed_at_epoch", 1002.0), ("observed_at_epoch", True),
            ("expires_at_epoch", 1001.0), ("expires_at_epoch", True),
            ("expires_at_epoch", "1002"), ("expires_at_epoch", float("nan")),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(KrakenProtectionDenied):
                build(self.broker, self.changed_ledger(lambda row: row.update({field: value})))()

    def test_source_expiring_during_final_identity_read_denies(self):
        now = [1001.0]
        original = self.broker._kraken_private_call
        def expire(method, params, *, category):
            result = original(method, params, category=category)
            if method == "GetApiKeyInfo" and self.broker.calls.count(method) == 2:
                now[0] = 1002.0
            return result
        self.broker._kraken_private_call = expire
        with self.assertRaisesRegex(KrakenProtectionDenied, "flat_ledger_expired_or_invalid"):
            build(self.broker, self.changed_ledger(lambda row: row.update(expires_at_epoch=1002.0)),
                  clock=lambda: now[0])()

    def test_orphan_open_order_is_not_flat_and_does_not_trigger_extra_reads(self):
        self.broker.orders = {STOP: Broker.order("stop-loss", "10", "1")}
        with self.assertRaisesRegex(KrakenProtectionDenied, "flat_open_order_inventory_not_empty"):
            build(self.broker, self.ledger)()
        self.assertNotIn("BalanceEx", self.broker.calls)

    def test_empty_first_order_page_does_not_claim_complete_inventory(self):
        original = self.broker._kraken_private_call
        def incomplete(method, params, *, category):
            result = original(method, params, category=category)
            if method == "OpenOrders":
                result["result"]["cursor"] = {"next": "unread-page"}
            return result
        self.broker._kraken_private_call = incomplete
        with self.assertRaises(KrakenProtectionDenied):
            build(self.broker, self.ledger)()

    def test_empty_margin_does_not_hide_spot_hold_credit_or_unknown_assets(self):
        rows = (
            {"XXBT": {"balance": "0.001", "hold_trade": "0"}},
            {"ZUSD": {"balance": "100", "hold_trade": "1"}},
            {"ZUSD": {"balance": "100", "hold_trade": "0", "credit": "10", "credit_used": "0"}},
            {"ZUSD": {"balance": "100", "hold_trade": "0", "credit": "10", "credit_used": "1"}},
            {"SOL": {"balance": "0", "hold_trade": "0"}},
            {"XBT.F": {"balance": "0", "hold_trade": "0"}},
            {"USD": {"balance": "0", "hold_trade": "0"}, "ZUSD": {"balance": "0", "hold_trade": "0"}},
        )
        for balances in rows:
            with self.subTest(balances=balances), self.assertRaises(KrakenProtectionDenied):
                self.broker.balances = balances
                build(self.broker, self.ledger)()

    def test_margin_exposure_denies_even_when_spot_and_orders_are_empty(self):
        self.broker.margin_positions = {"offline-margin-position": {"vol": "1"}}
        with self.assertRaisesRegex(KrakenProtectionDenied, "flat_margin_exposure_present"):
            build(self.broker, self.ledger)()

    def test_missing_unknown_or_malformed_balance_fields_deny(self):
        for row in (
            {}, {"balance": "0"}, {"balance": "0", "hold_trade": "0", "credit": "0"},
            {"balance": "0", "hold_trade": "0", "unknown": "0"},
            {"balance": True, "hold_trade": "0"}, {"balance": "-1", "hold_trade": "0"},
            {"balance": "NaN", "hold_trade": "0"}, {"balance": "0", "hold_trade": []},
        ):
            with self.subTest(row=row), self.assertRaises(KrakenProtectionDenied):
                self.broker.balances = {"ZUSD": row}
                build(self.broker, self.ledger)()

    def test_malformed_private_responses_deny_without_raw_error_text(self):
        original = self.broker._kraken_private_call
        for endpoint in ("BalanceEx", "OpenPositions"):
            for reply in ({}, {"error": [], "result": []},
                          {"error": ["private-response-canary"], "result": {}},
                          {"error": [], "result": {}, "unknown": "private-response-canary"}):
                def invalid(method, params, *, category):
                    result = original(method, params, category=category)
                    return reply if method == endpoint else result
                self.broker._kraken_private_call = invalid
                with self.subTest(endpoint=endpoint, reply=reply), self.assertRaises(KrakenProtectionDenied) as denied:
                    build(self.broker, self.ledger)()
                self.assertNotIn("private-response-canary", str(denied.exception))

    def test_changed_balances_or_ledger_revision_deny(self):
        original = self.broker._kraken_private_call
        def changed_balance(method, params, *, category):
            if method == "BalanceEx" and method in self.broker.calls:
                self.broker.balances["ZUSD"]["balance"] = "101"
            return original(method, params, category=category)
        self.broker._kraken_private_call = changed_balance
        with self.assertRaisesRegex(KrakenProtectionDenied, "readback_changed_or_stale"):
            build(self.broker, self.ledger)()
        self.broker._kraken_private_call = original
        self.ledger = FlatLedger()
        def changed_revision(row):
            if self.ledger.calls == 2:
                row["snapshot_id"] = "changed-revision"
        with self.assertRaisesRegex(KrakenProtectionDenied, "readback_changed_or_stale"):
            build(self.broker, self.changed_ledger(changed_revision))()

    def test_changed_account_client_or_transport_denies(self):
        for change in (
            lambda broker: setattr(broker, "connected", False),
            lambda broker: setattr(broker, "api", types.SimpleNamespace(key=KEY)),
            lambda broker: setattr(broker.api, "key", "different-synthetic-key"),
            lambda broker: setattr(broker, "user_id", "other-account"),
            lambda broker: setattr(broker, "_gateway_only_mode", True),
            lambda broker: setattr(broker, "_kraken_private_call", None),
        ):
            broker = Broker()
            broker.orders = {}
            original = broker._kraken_private_call
            def changed(method, params, *, category):
                result = original(method, params, category=category)
                if method == "BalanceEx":
                    change(broker)
                return result
            broker._kraken_private_call = changed
            with self.subTest(change=change), self.assertRaises(KrakenProtectionDenied):
                build(broker, FlatLedger())()
            self.assertEqual(broker.calls.count("BalanceEx"), 1)

    def test_actual_sqlite_native_ledger_flat_observations_integrate_without_writes(self):
        from bot.kraken_ledger_evidence import (
            ReviewedLedgerBinding, make_kraken_ledger_evidence_provider, offline_ledger_schema_sql,
        )

        class NativeFlatBroker(Broker):
            """Synthetic genesis deposit; only fixed private read endpoints exist."""

            def _kraken_private_call(self, method, params, *, category):
                if method in {"TradesHistory", "ClosedOrders", "Ledgers", "Balance"}:
                    assert category is CATEGORY
                    self.calls.append(method)
                    if method == "Balance":
                        assert params == {}
                        return {"error": [], "result": {"ZUSD": "100", "XXBT": "0"}}
                    assert params.get("with_cursor") == "true"
                    field = {"TradesHistory": "trades", "ClosedOrders": "closed", "Ledgers": "ledger"}[method]
                    rows = ({"offline-deposit": {"asset": "ZUSD", "amount": "100", "fee": "0",
                                                   "type": "deposit", "refid": "offline-deposit"}}
                            if method == "Ledgers" else {})
                    return {"error": [], "result": {field: rows, "cursor": {}}}
                return super()._kraken_private_call(method, params, category=category)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "offline-ledger.db"
            with sqlite3.connect(path) as db:
                for statement in offline_ledger_schema_sql():
                    db.execute(statement)
                db.execute("""INSERT INTO ledger_evidence_state
                    (broker, account_scope, api_key_sha256, account_sha256, schema_version,
                     revision, observed_at_epoch, history_from_genesis, unresolved_submission_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("kraken", "platform:kraken", KEY_PIN, IBAN_PIN, 1, "offline-revision", 1000.0, 1, 0))
            broker = NativeFlatBroker()
            broker.orders = {}
            binding = ReviewedLedgerBinding(
                broker, "platform:kraken", "independent-ledger", KEY_PIN, IBAN_PIN, path, root, CATEGORY,
            )
            # Exact-object review is an offline test double, never a production receipt.
            native = make_kraken_ledger_evidence_provider(
                binding, review_binding=lambda candidate: candidate is binding, clock=lambda: 1001.0,
            )
            observations = []
            def read_ledger():
                observation = native()
                observations.append(observation)
                return observation
            before = path.read_bytes()
            result = build(broker, read_ledger)()
            self.assertEqual(result["protection_status"], "verified_flat_no_exits_required")
            self.assertFalse(result["authorizes_orders"])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(observations), 2)
            self.assertNotEqual(observations[0]["evidence_id"], observations[1]["evidence_id"])
            self.assertEqual(observations[0]["snapshot_id"], observations[1]["snapshot_id"])
            self.assertEqual(broker.calls.count("BalanceEx"), 2)
            self.assertEqual(broker.calls.count("OpenPositions"), 2)
            self.assertEqual(set(broker.calls), {
                "GetApiKeyInfo", "Balance", "BalanceEx", "TradesHistory", "ClosedOrders",
                "Ledgers", "OpenOrders", "OpenPositions",
            })
            # Even the complete empty schema is insufficient without durable source state.
            with sqlite3.connect(path) as db:
                db.execute("DELETE FROM ledger_evidence_state")
            with self.assertRaisesRegex(KrakenProtectionDenied, "independent_ledger_read_failed"):
                build(broker, read_ledger)()

    def test_final_ledger_and_identity_cannot_replace_the_observed_transport(self):
        for stage in ("ledger", "identity"):
            for change in (
                lambda broker: setattr(broker, "api", types.SimpleNamespace(key=KEY)),
                lambda broker: setattr(broker, "_gateway_only_mode", True),
                lambda broker: setattr(broker, "_kraken_private_call", None),
            ):
                broker, ledger = Broker(), FlatLedger()
                broker.orders = {}
                original = broker._kraken_private_call
                def final_identity(method, params, *, category):
                    result = original(method, params, category=category)
                    if stage == "identity" and method == "GetApiKeyInfo" and broker.calls.count(method) == 2:
                        change(broker)
                    return result
                def final_ledger():
                    result = ledger()
                    if stage == "ledger" and ledger.calls == 2:
                        change(broker)
                    return result
                broker._kraken_private_call = final_identity
                with self.subTest(stage=stage, change=change), self.assertRaises(KrakenProtectionDenied):
                    build(broker, final_ledger)()
                self.assertEqual(broker.calls.count("GetApiKeyInfo"), 1 if stage == "ledger" else 2)


if __name__ == "__main__":
    unittest.main()
