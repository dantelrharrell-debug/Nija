"""Offline commissioning transitions; fixtures are NEVER production evidence."""
import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot.account_order_admission import AdmissionDenied
from bot.commissioning_gate import CommissioningGate
from bot.order_admission_policy import Candidate, CurrentFact, OrderOutcome, REQUIRED_CONTROLS
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES, PROOF_BY_SOURCE
from bot.startup_verification_plan import StartupVerificationPlan

NOW = 1_000_000.0


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class CommissioningGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.db"
        with sqlite3.connect(self.path) as conn:
            for table in ("open_positions", "completed_trades", "strategy_order_intents"):
                conn.execute("CREATE TABLE " + table + " (id INTEGER)")
            conn.execute("CREATE TABLE trade_ledger (user_id TEXT,order_id TEXT,position_id TEXT,action TEXT)")
            conn.execute("""CREATE TABLE pending_kraken_closes (broker TEXT,account_scope TEXT,
                user_id TEXT,order_id TEXT,state TEXT,matched_position_id TEXT)""")
        clock_patch = patch("bot.commissioning_gate.time.time", return_value=NOW)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.plan = StartupVerificationPlan(
            account_fingerprint="a" * 64, api_key_fingerprint="b" * 128,
            symbol="BTC-USD", pair="XXBTZUSD", budget_usd="25", entry_limit="1000",
            base_quantity="0.020", fee_rate_max="0.01", fee_cash_reserve_usd="0.20",
            stop_trigger="950", stop_limit="900", close_limit="990", base_quantum="0.001",
            minimum_base="0.001", minimum_quote="1", expires_at_epoch=NOW + 250,
        )
        self.candidate = Candidate("platform:kraken", self.plan.api_key_fingerprint, 3, self.plan.digest())
        self.operator_key = Ed25519PrivateKey.generate()
        self.status_key = Ed25519PrivateKey.generate()
        self.approval = {
            "contract": "nija.controlled-first-trade.v1", "approval_id": "offline-first-approval",
            "operator_id": "offline-operator", "account": self.candidate.account,
            "account_fingerprint": self.plan.account_fingerprint,
            "credential_fingerprint": self.candidate.credential_fingerprint,
            "writer_generation": 3, "plan_digest": self.plan.digest(), "release_id": "offline-release",
            "maximum_cash_debit_usd": "25", "approved_at_epoch": NOW - 1, "expires_at_epoch": NOW + 200,
        }
        self.status = {
            "contract": "nija.controlled-first-trade-status.v1", "approval_id": "offline-first-approval",
            "approval_sha256": "", "status": "active", "generation": 1,
            "observed_at_epoch": NOW, "expires_at_epoch": NOW + 60,
        }
        self.rows = {}
        for field in REQUIRED:
            source = SOURCES[field]
            self.rows[field] = {
                "account": self.candidate.account, "verified": True, "read_only": True,
                "scope_verified": True, "source": source, "provider_id": "offline-" + field,
                "evidence_id": "offline-evidence-" + field, "observed_at_epoch": NOW,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "complete_pagination_verified": True,
                    PROOF_BY_SOURCE[source]: True,
                },
            }
        general = self.rows["operator_authorization"]
        general.update(approval_id="offline-general-approval", status_generation=1, expires_at_epoch=NOW + 60)
        general["provenance"].update(
            signature_algorithm="Ed25519", approval_contract="nija.general-live-approval.v1",
            revocation_contract="nija.general-live-approval-status.v1",
        )
        self.lost_control = None
        self.fence_result = True
        self.evidence = None
        self.outcome = OrderOutcome(self.candidate.account, "none")
        self.gate = self.make_gate()
        self.gate.install_schema()

    def records(self):
        digest = hashlib.sha256(canonical(self.approval)).hexdigest()
        status = dict(self.status, approval_sha256=digest)
        return {
            "approval": self.sign(self.approval, self.operator_key),
            "status": self.sign(status, self.status_key),
        }

    @staticmethod
    def sign(payload, key):
        return {"payload": payload, "signature": base64.b64encode(key.sign(canonical(payload))).decode()}

    def collect(self, candidate, conn):
        conn.execute("SELECT COUNT(*) FROM trade_ledger").fetchone()
        return ({
            field: CurrentFact(candidate, field != self.lost_control, self.clock(), "offline-only-" + field)
            for field in REQUIRED_CONTROLS
        }, self.outcome)

    def make_gate(self, **changes):
        args = dict(
            observations=lambda candidate, conn: self.rows,
            trusted_provider_ids={field: "offline-" + field for field in REQUIRED},
            execution_reader=lambda candidate, plan, conn: self.evidence,
            read_approval=self.records,
            operator_public_keys={"offline-operator": self.operator_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            )},
            status_public_key=self.status_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw,
            ),
            release_id="offline-release", maximum_cash_debit_usd="25",
            account_scope=self.candidate.account, account_fingerprint=self.plan.account_fingerprint,
            credential_fingerprint=self.candidate.credential_fingerprint, independently_reviewed=True,
        )
        args.update(changes)
        return CommissioningGate(self.path, self.collect, lambda candidate: self.fence_result, **args)

    def consume(self):
        return self.gate.consume_first_trade(self.candidate, self.plan)

    def fill(self):
        self.evidence = {
            "candidate": self.candidate, "account_fingerprint": self.plan.account_fingerprint,
            "client_order_id": self.plan.order_parameters("entry")["cl_ord_id"],
            "entry_parameters": self.plan.order_parameters("entry"),
            "source": "canonical_confirmed_fill", "stage": "FILL_VERIFY", "proof_kind": "execution_probe",
            "authoritative_broker_verified": True, "ledger_reconciled": True, "protective_exit_verified": True,
            "synthetic": False, "simulated": False, "historical": False,
            "broker_event_at_epoch": NOW + 1, "verified_at_epoch": NOW + 2,
            "broker_order_id": "offline-order", "protective_order_id": "offline-stop",
            "filled_base_quantity": "0.020", "cash_debit_usd": "20.4",
            "owned_base_quantity": "0.020", "protected_base_quantity": "0.020",
        }
        self.clock.return_value = NOW + 2
        self.outcome = OrderOutcome(
            self.candidate.account, "verified", NOW + 1, NOW + 2, "offline-order", True, True,
        )

    def test_no_fill_pretrade_then_exact_first_order_then_posttrade(self):
        ready = self.gate.inspect_pretrade(self.candidate, self.plan)
        self.assertEqual(ready.state, "PRETRADE_READY")
        self.assertFalse(ready.allow_new_orders)
        self.assertFalse(ready.allow_controlled_first_trade)
        approved = self.gate.inspect_first_trade(self.candidate, self.plan)
        self.assertTrue(approved.allow_controlled_first_trade)
        self.assertFalse(approved.allow_new_orders)
        permit = self.consume()
        self.assertEqual(permit.candidate, self.candidate)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT state FROM commissioning_attempts").fetchone(),
                             ("CONTROLLED_FIRST_TRADE",))
            self.assertEqual(conn.execute("SELECT state FROM account_entry_reservations").fetchone(),
                             ("submitting",))
        with self.assertRaises(AdmissionDenied):
            self.gate.verify_posttrade(self.candidate, self.plan)
        self.fill()
        result = self.gate.verify_posttrade(self.candidate, self.plan)
        self.assertEqual(result.state, "POSTTRADE_VERIFIED")
        self.assertFalse(result.allow_new_orders)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT state FROM commissioning_attempts").fetchone(),
                             ("POSTTRADE_VERIFIED",))
            self.assertEqual(conn.execute("SELECT state FROM account_entry_reservations").fetchone(),
                             ("submitting",))
        with self.assertRaises(AdmissionDenied):
            self.consume()

    def test_unreviewed_gate_cannot_be_constructed(self):
        with self.assertRaisesRegex(AdmissionDenied, "independent_review"):
            self.make_gate(independently_reviewed=False)

    def test_general_approval_does_not_replace_exact_first_order_approval(self):
        self.assertEqual(self.gate.inspect_pretrade(self.candidate, self.plan).state, "PRETRADE_READY")
        self.gate.read_approval = lambda: {}
        with self.assertRaises(AdmissionDenied):
            self.consume()

    def test_first_order_approval_does_not_replace_general_signed_authorization(self):
        del self.rows["operator_authorization"]["provenance"]["signature_algorithm"]
        with self.assertRaisesRegex(AdmissionDenied, "signed_general"):
            self.consume()

    def test_every_independent_pretrade_check_is_required(self):
        for field in REQUIRED:
            with self.subTest(field=field):
                self.rows[field]["verified"] = False
                with self.assertRaisesRegex(AdmissionDenied, field):
                    self.consume()
                self.rows[field]["verified"] = True

    def test_every_existing_order_control_remains_required(self):
        for field in REQUIRED_CONTROLS:
            with self.subTest(field=field):
                self.lost_control = field
                with self.assertRaisesRegex(AdmissionDenied, field):
                    self.consume()
        self.lost_control = None

    def test_denials_do_not_consume_or_submit(self):
        self.fence_result = False
        with self.assertRaises(AdmissionDenied):
            self.consume()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM commissioning_attempts").fetchone(), (0,))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM account_entry_reservations").fetchone(), (0,))

    def test_bad_signature_revocation_and_unbound_approval_block(self):
        records = self.records()
        records["approval"]["signature"] = base64.b64encode(bytes(64)).decode()
        self.gate.read_approval = lambda: records
        with self.assertRaisesRegex(AdmissionDenied, "signature_invalid"):
            self.consume()
        self.gate.read_approval = self.records
        for status in ("revoked", "unknown"):
            self.status["status"] = status
            with self.assertRaisesRegex(AdmissionDenied, "revoked"):
                self.consume()
        self.status["status"] = "active"
        for field, value in (
            ("plan_digest", "c" * 64), ("writer_generation", 4), ("account", "user:other:kraken"),
            ("credential_fingerprint", "c" * 128), ("release_id", "other-release"),
        ):
            original = self.approval[field]
            with self.subTest(field=field):
                self.approval[field] = value
                with self.assertRaisesRegex(AdmissionDenied, "binding_mismatch"):
                    self.consume()
                self.approval[field] = original

    def test_approval_budget_and_expiry_are_enforced(self):
        for ceiling in ("0", "20", "26"):
            self.approval["maximum_cash_debit_usd"] = ceiling
            with self.assertRaises(AdmissionDenied):
                self.consume()
        self.approval["maximum_cash_debit_usd"] = "25"
        self.approval["expires_at_epoch"] = NOW
        with self.assertRaisesRegex(AdmissionDenied, "expired"):
            self.consume()

    def test_signed_approval_uses_private_payload_snapshot(self):
        self.approval["expires_at_epoch"] = NOW + 1
        records = self.records()
        self.gate.read_approval = lambda: records

        def mutate_after_readback():
            records["approval"]["payload"]["expires_at_epoch"] = NOW + 200
            return NOW + 2

        self.clock.side_effect = mutate_after_readback
        with self.assertRaisesRegex(AdmissionDenied, "future_expired_or_stale"):
            self.gate._approval(self.candidate, self.plan)

    def test_slow_pretrade_cannot_outlive_signed_approval(self):
        def slow(candidate, conn):
            self.clock.return_value = NOW + 61
            rows = json.loads(json.dumps(self.rows))
            for row in rows.values():
                row["observed_at_epoch"] = NOW + 61
            rows["operator_authorization"]["expires_at_epoch"] = NOW + 100
            return rows
        self.gate.observations = slow
        with self.assertRaisesRegex(AdmissionDenied, "expired_during_pretrade"):
            self.consume()

    def test_restart_new_approval_and_rotated_writer_cannot_replay(self):
        permit = self.consume()
        restarted = self.make_gate()
        self.approval["approval_id"] = self.status["approval_id"] = "replacement-approval"
        with self.assertRaises(AdmissionDenied):
            restarted.consume_first_trade(self.candidate, self.plan)
        for method in (restarted.reserve, restarted.consume):
            with self.assertRaises(AdmissionDenied):
                method(self.candidate if method == restarted.reserve else permit)
        with self.assertRaises(AdmissionDenied):
            restarted.consume_first_trade(replace(self.candidate, writer_generation=4), self.plan)

    def test_each_posttrade_provenance_and_reconciliation_check_is_required(self):
        self.consume()
        self.fill()
        changes = {
            "source": "heartbeat_trade", "stage": "ORDER_VERIFY", "proof_kind": "auth_probe",
            "candidate": replace(self.candidate, account="user:other:kraken"),
            "account_fingerprint": "c" * 64, "client_order_id": "other-order",
            "entry_parameters": {}, "authoritative_broker_verified": False,
            "ledger_reconciled": False, "protective_exit_verified": False,
            "synthetic": True, "simulated": True, "historical": True,
            "broker_order_id": "", "protective_order_id": "",
            "filled_base_quantity": "0.01", "cash_debit_usd": "26",
            "protected_base_quantity": "0.019",
        }
        for field, value in changes.items():
            original = self.evidence[field]
            with self.subTest(field=field):
                self.evidence[field] = value
                with self.assertRaises(AdmissionDenied):
                    self.gate.verify_posttrade(self.candidate, self.plan)
                self.evidence[field] = original

    def test_historical_fill_cannot_inherit_fresh_verification_clock(self):
        self.consume()
        self.fill()
        self.evidence["broker_event_at_epoch"] = NOW - 1
        with self.assertRaisesRegex(AdmissionDenied, "not_fresh_for_this_attempt"):
            self.gate.verify_posttrade(self.candidate, self.plan)

    def test_completed_state_requires_new_authenticated_readback(self):
        self.consume()
        self.fill()
        self.gate.verify_posttrade(self.candidate, self.plan)
        self.evidence = None
        with self.assertRaises(AdmissionDenied):
            self.gate.verify_posttrade(self.candidate, self.plan)

    def test_completed_state_rejects_changed_order_or_event_time(self):
        self.consume()
        self.fill()
        self.gate.verify_posttrade(self.candidate, self.plan)
        original_order_id = self.evidence["broker_order_id"]
        original_event = self.evidence["broker_event_at_epoch"]

        for field, value, order_id, event in (
            ("broker_order_id", "different-order", "different-order", original_event),
            ("broker_event_at_epoch", original_event + 0.5, original_order_id, original_event + 0.5),
        ):
            with self.subTest(field=field):
                self.evidence[field] = value
                self.outcome = OrderOutcome(
                    self.candidate.account, "verified", event, NOW + 2, order_id, True, True,
                )
                with self.assertRaisesRegex(AdmissionDenied, "readback_changed"):
                    self.gate.verify_posttrade(self.candidate, self.plan)
                self.evidence[field] = (
                    original_order_id if field == "broker_order_id" else original_event
                )
                self.outcome = OrderOutcome(
                    self.candidate.account, "verified", original_event, NOW + 2, original_order_id, True, True,
                )

        self.assertEqual(self.gate.verify_posttrade(self.candidate, self.plan).state, "POSTTRADE_VERIFIED")
        with sqlite3.connect(self.path) as conn:
            pinned = conn.execute(
                "SELECT broker_order_id,broker_event_at FROM commissioning_attempts"
            ).fetchone()
        self.assertEqual(pinned, (original_order_id, original_event))

    def test_broker_fill_without_matching_ledger_outcome_is_blocked(self):
        self.consume()
        self.fill()
        self.outcome = OrderOutcome(self.candidate.account, "none")
        with self.assertRaisesRegex(AdmissionDenied, "ledger_outcome_mismatch"):
            self.gate.verify_posttrade(self.candidate, self.plan)

    def test_unresolved_existing_kraken_close_cannot_be_overridden(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO pending_kraken_closes VALUES (?,?,?,?,?,?)",
                         ("kraken", self.candidate.account, "platform", "unresolved", "pending", None))
        with self.assertRaisesRegex(AdmissionDenied, "unresolved_kraken_fill"):
            self.consume()

    def test_unauthorized_schema_missing_and_corrupt_database_fail_closed(self):
        missing = Path(self.temp.name) / "missing.db"
        self.gate.ledger = missing
        with self.assertRaises(AdmissionDenied):
            self.consume()
        self.assertFalse(missing.exists())
        missing.write_bytes(b"offline-corrupt-db")
        with self.assertRaises(sqlite3.DatabaseError):
            self.consume()

    def test_commissioning_schema_migration_rolls_back_atomically_and_recovers(self):
        path = Path(self.temp.name) / "migration.db"
        with sqlite3.connect(path) as conn:
            for table in ("open_positions", "completed_trades", "strategy_order_intents"):
                conn.execute("CREATE TABLE " + table + " (id INTEGER)")
            conn.execute("CREATE TABLE trade_ledger (user_id TEXT, order_id TEXT, position_id TEXT, action TEXT)")
            conn.execute("CREATE VIEW commissioning_attempts AS SELECT 1 AS incompatible")
        gate = self.make_gate()
        gate.ledger = path
        with self.assertRaisesRegex(AdmissionDenied, "migration_invalid:commissioning_attempts"):
            gate.install_schema()
        with sqlite3.connect(path) as conn:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_entry_reservations'"
            ).fetchone())
            self.assertEqual(conn.execute(
                "SELECT type FROM sqlite_master WHERE name='commissioning_attempts'"
            ).fetchone(), ("view",))
            conn.execute("DROP VIEW commissioning_attempts")
        gate.install_schema()
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute(
                "SELECT type FROM sqlite_master WHERE name='account_entry_reservations'"
            ).fetchone(), ("table",))
            self.assertEqual(conn.execute(
                "SELECT type FROM sqlite_master WHERE name='commissioning_attempts'"
            ).fetchone(), ("table",))


if __name__ == "__main__":
    unittest.main()
