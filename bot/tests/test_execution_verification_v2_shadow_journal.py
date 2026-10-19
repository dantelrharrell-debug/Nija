"""CI-discovered, offline tests: v2 shadow inbox NEVER authorizes trading."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from bot.execution_verification_v2_shadow_journal import (
    ShadowEvidenceError, initialize_shadow_journal, persist_shadow_intent,
    bind_shadow_broker_ack, persist_shadow_fill_candidate, shadow_journal_counts,
)


class TestV2DurableShadowJournal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "shadow-evidence.db"
        initialize_shadow_journal(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def intent(self, **overrides):
        params = {
            "venue": "kraken", "account_fingerprint": "account-A",
            "tenant_fingerprint": "tenant-A", "client_order_id": "client-1",
            "symbol": "BABY-USD", "side": "buy",
            "requested_qty": "3", "request_digest": "a" * 64,
            "writer_generation": 5,
        }
        params.update(overrides)
        return persist_shadow_intent(self.path, **params)

    def ack(self, **overrides):
        params = {
            "venue": "kraken", "account_fingerprint": "account-A",
            "tenant_fingerprint": "tenant-A", "client_order_id": "client-1",
            "broker_order_id": "broker-100",
        }
        params.update(overrides)
        return bind_shadow_broker_ack(self.path, **params)

    def fill(self, **overrides):
        params = {
            "venue": "kraken", "account_fingerprint": "account-A",
            "tenant_fingerprint": "tenant-A", "client_order_id": "client-1",
            "broker_order_id": "broker-100", "symbol": "BABY-USD", "side": "buy",
            "execution_id": "execution-1", "event_digest": "b" * 64,
            "fill_qty": "1", "fill_price": "7.50", "cumulative_qty": "1",
            "source": "private_ws",
        }
        params.update(overrides)
        return persist_shadow_fill_candidate(self.path, **params)

    def _prepared(self):
        self.assertEqual(self.intent(), "shadow_intent_persisted")
        self.assertEqual(self.ack(), "shadow_ack_recorded_not_fill")

    def test_empty_journal_is_never_trading_authority(self):
        result = shadow_journal_counts(self.path)
        self.assertEqual(result["intents"], 0)
        self.assertEqual(result["fill_candidates"], 0)
        self.assertTrue(result["shadow_only"])
        self.assertFalse(result["execution_authority_granted"])
        self.assertFalse(result["trading_ledger_mutated"])

    def test_durable_intent_duplicate_is_idempotent(self):
        self.assertEqual(self.intent(), "shadow_intent_persisted")
        self.assertEqual(self.intent(), "duplicate_intent")
        self.assertEqual(shadow_journal_counts(self.path)["intents"], 1)

    def test_conflicting_reuse_of_client_order_id_is_refused(self):
        self.intent()
        with self.assertRaisesRegex(ShadowEvidenceError, "conflicting_client_order_id"):
            self.intent(request_digest="c" * 64)

    def test_cross_tenant_intent_collision_is_refused(self):
        self.intent()
        with self.assertRaisesRegex(ShadowEvidenceError, "conflicting_client_order_id"):
            self.intent(tenant_fingerprint="tenant-B")

    def test_broker_ack_is_not_fill_and_is_idempotent(self):
        self._prepared()
        self.assertEqual(self.ack(), "duplicate_ack")
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 0)

    def test_broker_ack_conflict_is_refused(self):
        self._prepared()
        with self.assertRaisesRegex(ShadowEvidenceError, "conflicting_broker_order_id"):
            self.ack(broker_order_id="broker-200")

    def test_broker_order_id_cannot_be_reused_for_another_intent(self):
        self._prepared()
        self.intent(client_order_id="client-2", request_digest="c" * 64)
        with self.assertRaisesRegex(ShadowEvidenceError, "broker_order_id_collision"):
            self.ack(client_order_id="client-2")
        self.assertEqual(shadow_journal_counts(self.path)["intents"], 2)

    def test_fill_requires_prior_mapped_broker_ack(self):
        self.intent()
        with self.assertRaisesRegex(ShadowEvidenceError, "broker_order_or_market_mismatch"):
            self.fill()
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 0)

    def test_partial_fills_persist_and_cumulative_qty_is_exact(self):
        self._prepared()
        self.assertEqual(self.fill(), "fill_candidate_stored_unreconciled")
        self.assertEqual(self.fill(
            execution_id="execution-2", event_digest="c" * 64,
            fill_qty="1.5", cumulative_qty="2.5"
        ), "fill_candidate_stored_unreconciled")
        result = shadow_journal_counts(self.path)
        self.assertEqual(result["fill_candidates"], 2)
        self.assertFalse(result["execution_authority_granted"])

    def test_duplicate_fill_is_only_one_shadow_candidate(self):
        self._prepared()
        self.fill()
        self.assertEqual(self.fill(), "duplicate_fill_candidate")
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 1)

    def test_conflicting_duplicate_execution_id_is_quarantined(self):
        self._prepared()
        self.fill()
        with self.assertRaisesRegex(ShadowEvidenceError, "conflicting_execution_id"):
            self.fill(event_digest="d" * 64)

    def test_same_execution_digest_with_changed_fill_payload_is_not_duplicate(self):
        self._prepared()
        self.fill()
        for change in (
            {"fill_qty": "2"},
            {"fill_price": "8.00"},
            {"cumulative_qty": "2"},
            {"source": "authenticated_rest"},
        ):
            with self.assertRaisesRegex(ShadowEvidenceError, "conflicting_execution_id"):
                self.fill(**change)
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 1)

    def test_cumulative_sequence_gap_fails_closed(self):
        self._prepared()
        with self.assertRaisesRegex(ShadowEvidenceError, "fill_sequence_gap"):
            self.fill(fill_qty="1", cumulative_qty="2")
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 0)

    def test_overfill_fails_closed(self):
        self._prepared()
        with self.assertRaisesRegex(ShadowEvidenceError, "overfill_candidate"):
            self.fill(fill_qty="4", cumulative_qty="4")

    def test_fill_from_wrong_tenant_is_quarantined(self):
        self._prepared()
        with self.assertRaisesRegex(ShadowEvidenceError, "unknown_or_cross_tenant_intent"):
            self.fill(tenant_fingerprint="tenant-B")

    def test_fill_identity_mismatch_is_quarantined(self):
        self._prepared()
        for change in ({"symbol": "ETH-USD"}, {"side": "sell"}, {"broker_order_id": "other"}):
            with self.assertRaisesRegex(ShadowEvidenceError, "broker_order_or_market_mismatch"):
                self.fill(**change)

    def test_nan_or_infinite_fill_is_rejected_without_record(self):
        self._prepared()
        for change in ({"fill_qty": "NaN"}, {"fill_price": "Infinity"}, {"cumulative_qty": "nan"}):
            with self.assertRaisesRegex(ShadowEvidenceError, "invalid_positive_quantity"):
                self.fill(**change)
        self.assertEqual(shadow_journal_counts(self.path)["fill_candidates"], 0)

    def test_input_path_must_be_explicit_and_preinitialized(self):
        unknown = Path(self.temp.name) / "never-created-shadow.sqlite"
        with self.assertRaisesRegex(ShadowEvidenceError, "shadow_database_uninitialized"):
            persist_shadow_intent(
                unknown, venue="kraken", account_fingerprint="account-A",
                tenant_fingerprint="tenant-A", client_order_id="client-1",
                symbol="BABY-USD", side="buy", requested_qty="3",
                request_digest="a"*64, writer_generation=5,
            )

    def test_existing_live_style_ledger_is_never_modified(self):
        ledger = Path(self.temp.name) / "unrelated_shadow_ledger.db"
        with sqlite3.connect(ledger) as conn:
            conn.execute("CREATE TABLE real_trades (trade_id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO real_trades VALUES ('existing-trade')")
        with self.assertRaisesRegex(ShadowEvidenceError, "shadow_database_identity_mismatch"):
            initialize_shadow_journal(ledger)
        with self.assertRaisesRegex(ShadowEvidenceError, "shadow_database_identity_mismatch"):
            shadow_journal_counts(ledger)
        with sqlite3.connect(ledger) as conn:
            self.assertEqual(conn.execute(
                "SELECT trade_id FROM real_trades"
            ).fetchall(), [("existing-trade",)])
            self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], 0)

    def test_new_production_style_ledger_path_cannot_be_initialised(self):
        production_path = Path(self.temp.name) / "trade_ledger.db"
        with self.assertRaisesRegex(ShadowEvidenceError, "shadow_database_path_invalid"):
            initialize_shadow_journal(production_path)
        self.assertFalse(production_path.exists())

    def test_schema_reinitialization_requires_known_shadow_identity(self):
        initialize_shadow_journal(self.path)
        self.intent()
        initialize_shadow_journal(self.path)
        self.assertEqual(shadow_journal_counts(self.path)["intents"], 1)

    def test_import_and_schema_have_no_trading_side_effects(self):
        self._prepared()
        self.fill()
        result = shadow_journal_counts(self.path)
        self.assertEqual(result["intents"], 1)
        self.assertEqual(result["fill_candidates"], 1)
        self.assertEqual(result["execution_authority_granted"], False)
        self.assertEqual(result["trading_ledger_mutated"], False)


if __name__ == "__main__":
    unittest.main()
