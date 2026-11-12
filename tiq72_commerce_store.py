"""Isolated, disabled-by-default TIQ72 persistence primitives.

No Flask route or live Stripe client is registered here. Database must be durable;
never use ephemeral Render filesystem for production entitlements.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS tiq72_runs (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, version TEXT NOT NULL,
 digest TEXT NOT NULL, canonical_json TEXT NOT NULL, score_json TEXT NOT NULL,
 created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tiq72_reservations (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES tiq72_runs(id),
 owner_id TEXT NOT NULL, stripe_session TEXT UNIQUE, status TEXT NOT NULL
 CHECK(status IN ('reserved','checkout_created','paid','refunded','disputed')),
 created_at INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS tiq72_one_reservation_per_run_owner
 ON tiq72_reservations(run_id,owner_id);
CREATE TABLE IF NOT EXISTS tiq72_events (
 event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
 reservation_id TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tiq72_entitlements (
 reservation_id TEXT PRIMARY KEY REFERENCES tiq72_reservations(id),
 owner_id TEXT NOT NULL, status TEXT NOT NULL
 CHECK(status IN ('active','revoked')), updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tiq72_reports (
 reservation_id TEXT PRIMARY KEY REFERENCES tiq72_entitlements(reservation_id),
 report_json TEXT NOT NULL, created_at INTEGER NOT NULL);
"""

class CommerceDenied(ValueError):
    pass

class Tiq72Store:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def save_run(self, owner_id, version, canonical_run, score):
        if not owner_id or version != "v515-72-decisions":
            raise CommerceDenied("invalid_run_identity")
        if not isinstance(canonical_run, dict) or not isinstance(score, dict):
            raise CommerceDenied("authoritative_result_required")
        challenges = canonical_run.get("challenges")
        if not isinstance(challenges, list) or len(challenges) != 6 or any(
            not isinstance(c, list) or len(c) != 12 for c in challenges
        ):
            raise CommerceDenied("72_decisions_required")
        # The caller MUST be a trusted scoring service, never an untrusted browser.
        raw = json.dumps(canonical_run, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        run_id = str(uuid.uuid4())
        with self.db:
            self.db.execute("INSERT INTO tiq72_runs VALUES (?,?,?,?,?,?,?)",
                (run_id, owner_id, version, digest, raw, json.dumps(score), int(time.time())))
        return run_id

    def reserve(self, run_id, owner_id, adult_attested):
        if adult_attested is not True or not owner_id:
            raise CommerceDenied("adult_identity_required")
        with self.db:
            row = self.db.execute("SELECT owner_id FROM tiq72_runs WHERE id=?", (run_id,)).fetchone()
            if not row or row[0] != owner_id:
                raise CommerceDenied("run_not_owned")
            prior = self.db.execute(
                "SELECT id FROM tiq72_reservations WHERE run_id=? AND owner_id=?",
                (run_id,owner_id)).fetchone()
            if prior:
                return prior[0]
            rid = str(uuid.uuid4())
            self.db.execute("INSERT INTO tiq72_reservations VALUES (?,?,?,?,?,?)",
                (rid,run_id,owner_id,None,"reserved",int(time.time())))
            return rid

    def attach_session(self, reservation_id, session_id):
        if not isinstance(session_id,str) or not session_id.startswith(("cs_test_","cs_live_")):
            raise CommerceDenied("invalid_session")
        with self.db:
            row=self.db.execute("SELECT stripe_session FROM tiq72_reservations WHERE id=?",
                                (reservation_id,)).fetchone()
            if not row or (row[0] and row[0]!=session_id):
                raise CommerceDenied("reservation_conflict")
            self.db.execute("UPDATE tiq72_reservations SET stripe_session=?,status='checkout_created' WHERE id=? AND status IN ('reserved','checkout_created')",
                            (session_id,reservation_id))

    def record_verified_event(self, event_id, event_type, reservation_id, session_id,
                              *, verified_paid=False, verified_reversal=False):
        """Only call after raw-body Stripe signature verification AND Stripe object reconciliation.

        Payment validation must confirm mode, price, product, currency, amount,
        livemode expectation, customer, session and payment-intent status.
        """
        if not event_id or not reservation_id or not session_id:
            raise CommerceDenied("missing_verified_identity")
        if event_type not in ("checkout.session.completed","checkout.session.async_payment_succeeded",
                              "charge.refunded","charge.dispute.created"):
            raise CommerceDenied("unsupported_event")
        grant = event_type in ("checkout.session.completed","checkout.session.async_payment_succeeded")
        if (grant and not verified_paid) or (not grant and not verified_reversal):
            raise CommerceDenied("payment_reconciliation_required")
        with self.db:
            row=self.db.execute("SELECT owner_id,stripe_session,status FROM tiq72_reservations WHERE id=?",
                                (reservation_id,)).fetchone()
            if not row or row[1]!=session_id:
                raise CommerceDenied("session_mismatch")
            seen=self.db.execute("SELECT 1 FROM tiq72_events WHERE event_id=?",(event_id,)).fetchone()
            if seen:
                return False
            self.db.execute("INSERT INTO tiq72_events VALUES (?,?,?,?)",
                            (event_id,event_type,reservation_id,int(time.time())))
            # Replayed/out-of-order completion must never restore a reversed purchase.
            if grant and row[2] not in ("refunded","disputed"):
                self.db.execute("UPDATE tiq72_reservations SET status='paid' WHERE id=?",(reservation_id,))
                self.db.execute("""INSERT INTO tiq72_entitlements VALUES (?,?,?,?)
                    ON CONFLICT(reservation_id) DO UPDATE SET
                    status=CASE WHEN status='revoked' THEN 'revoked' ELSE 'active' END,
                    updated_at=excluded.updated_at""",
                    (reservation_id,row[0],"active",int(time.time())))
            elif not grant:
                status="refunded" if event_type=="charge.refunded" else "disputed"
                self.db.execute("UPDATE tiq72_reservations SET status=? WHERE id=?",(status,reservation_id))
                self.db.execute("UPDATE tiq72_entitlements SET status='revoked',updated_at=? WHERE reservation_id=?",
                                (int(time.time()),reservation_id))
            return True

    def save_report(self, reservation_id, report):
        with self.db:
            row=self.db.execute("SELECT status FROM tiq72_entitlements WHERE reservation_id=?",
                                (reservation_id,)).fetchone()
            if not row or row[0]!="active":
                raise CommerceDenied("active_entitlement_required")
            self.db.execute("INSERT OR IGNORE INTO tiq72_reports VALUES (?,?,?)",
                            (reservation_id,json.dumps(report),int(time.time())))

    def get_report(self, reservation_id, owner_id):
        row=self.db.execute("""SELECT p.report_json FROM tiq72_reports p
            JOIN tiq72_entitlements e ON e.reservation_id=p.reservation_id
            WHERE p.reservation_id=? AND e.owner_id=? AND e.status='active'""",
            (reservation_id,owner_id)).fetchone()
        if not row:
            raise CommerceDenied("report_unavailable")
        return json.loads(row[0])
