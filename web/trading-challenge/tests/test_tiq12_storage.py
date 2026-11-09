"""Review-only SQLite schema tests with fictional data. No provider or IONOS calls."""
import pathlib
import sqlite3
import unittest

SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "server" / "tiq12-storage.schema.sql"

class TestTiq12Storage(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA.read_text())
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("INSERT INTO tiq12_runs VALUES (?,?,?,?,?,?,?,?)",
                        ("run_12345", "nija-trading-iq-12-v1", "a"*64, "b"*64,
                         "[0,1,0,1,0,1,0,1,0,1,0,1]", 1, "2026-11-09T00:00:00Z",
                         "2026-11-09T01:00:00Z"))
        self.db.execute("INSERT INTO tiq12_checkout_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("rsv_1", "run_12345", "idem_1", None, "price_test_1", "prod_test_1",
                         100, "usd", 0, "reserved", "2026-11-09T00:00:00Z",
                         "2026-11-10T00:00:00Z"))

    def commit_checkout(self, session="cs_test_123456789012"):
        self.db.execute("UPDATE tiq12_checkout_reservations SET checkout_session_id=?, state=? WHERE reservation_id=?",
                        (session, "created", "rsv_1"))

    def event(self, event="evt_abc123", session="cs_test_123456789012"):
        self.db.execute("INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)",
                        (event, "checkout.session.completed", session, "c"*64,
                         "2026-11-09T02:00:00Z", "2026-11-09T02:00:00Z", "applied"))

    def verified_payment(self, session="cs_test_123456789012"):
        self.db.execute("INSERT INTO tiq12_verified_payments VALUES (?,?,?,?,?,?,?,?,?)",
                        (session, "rsv_1", "pi_abc123", "ch_abc123", "evt_abc123",
                         100, "usd", 0, "2026-11-09T02:00:00Z"))

    def grant(self, run="run_12345", session="cs_test_123456789012"):
        self.db.execute("INSERT INTO tiq12_report_entitlements VALUES (?,?,?,?,?,?)",
                        (run, session, "granted", "2026-11-09T02:00:00Z",
                         "2027-11-09T02:00:00Z", None))

    def test_unique_per_run_checkout_and_idempotency(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO tiq12_checkout_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            ("rsv_2", "run_12345", "idem_2", None, "price_test_1", "prod_test_1",
                             100, "usd", 0, "reserved", "2026-11-09T00:00:00Z",
                             "2026-11-10T00:00:00Z"))
        self.commit_checkout()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE tiq12_checkout_reservations SET checkout_session_id='cs_test_other' WHERE reservation_id='rsv_1'")

    def test_reject_live_or_incorrect_amount(self):
        for sql in ["UPDATE tiq12_checkout_reservations SET livemode=1 WHERE reservation_id='rsv_1'",
                    "UPDATE tiq12_checkout_reservations SET amount_cents=99 WHERE reservation_id='rsv_1'",
                    "UPDATE tiq12_checkout_reservations SET currency='eur' WHERE reservation_id='rsv_1'"]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)

    def test_webhook_event_deduplication(self):
        self.event()
        with self.assertRaises(sqlite3.IntegrityError):
            self.event()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE tiq12_webhook_events SET event_type='spoof' WHERE stripe_event_id='evt_abc123'")

    def test_payment_must_match_reservation_and_event(self):
        self.commit_checkout()
        self.event()
        with self.assertRaises(sqlite3.IntegrityError):
            self.verified_payment("cs_test_other")
        self.verified_payment()
        with self.assertRaises(sqlite3.IntegrityError):
            self.verified_payment()

    def test_reversed_before_paid_cannot_grant(self):
        self.commit_checkout()
        self.event()
        self.verified_payment()
        self.db.execute("INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)",
                        ("evt_refund", "charge.refunded", "cs_test_123456789012", "e"*64,
                         "2026-11-09T03:00:00Z", "2026-11-09T03:00:00Z", "applied"))
        self.db.execute("INSERT INTO tiq12_revocations VALUES (?,?,?,?)",
                        ("cs_test_123456789012", "evt_refund", "refund", "2026-11-09T03:00:00Z"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.grant()

    def test_refund_revokes_and_cannot_regrant(self):
        self.commit_checkout()
        self.event()
        self.verified_payment()
        self.grant()
        self.db.execute("INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)",
                        ("evt_refund", "charge.refunded", "cs_test_123456789012", "e"*64,
                         "2026-11-09T03:00:00Z", "2026-11-09T03:00:00Z", "applied"))
        self.db.execute("INSERT INTO tiq12_revocations VALUES (?,?,?,?)",
                        ("cs_test_123456789012", "evt_refund", "refund", "2026-11-09T03:00:00Z"))
        row = self.db.execute("SELECT status,revoked_at FROM tiq12_report_entitlements").fetchone()
        self.assertEqual(row, ("revoked", "2026-11-09T03:00:00Z"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE tiq12_report_entitlements SET status='granted', revoked_at=NULL WHERE run_id='run_12345'")

    def test_manifest_and_age_fail_closed(self):
        for age, version in [(0, "nija-trading-iq-12-v1"), (1, "six-round")]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("INSERT INTO tiq12_runs VALUES (?,?,?,?,?,?,?,?)",
                                ("run_new", version, "a"*64, "b"*64,
                                 "[0,1,0,1,0,1,0,1,0,1,0,1]", age, "2026", "2026"))


    def test_wrong_run_cannot_receive_another_run_purchase(self):
        self.commit_checkout()
        self.event()
        self.verified_payment()
        self.db.execute("INSERT INTO tiq12_runs VALUES (?,?,?,?,?,?,?,?)",
                        ("run_other", "nija-trading-iq-12-v1", "d"*64, "e"*64,
                         "[0,1,0,1,0,1,0,1,0,1,0,1]", 1, "2026", "2026"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.grant("run_other")

    def test_backup_restore_preserves_dispute_revocation(self):
        self.commit_checkout()
        self.event()
        self.verified_payment()
        self.grant()
        self.db.execute("INSERT INTO tiq12_webhook_events VALUES (?,?,?,?,?,?,?)",
                        ("evt_dispute", "charge.dispute.created", "cs_test_123456789012", "f"*64,
                         "2026-11-09T04:00:00Z", "2026-11-09T04:00:00Z", "applied"))
        self.db.execute("INSERT INTO tiq12_revocations VALUES (?,?,?,?)",
                        ("cs_test_123456789012", "evt_dispute", "dispute", "2026-11-09T04:00:00Z"))
        self.db.commit()
        restored = sqlite3.connect(":memory:")
        self.db.backup(restored)
        restored.execute("PRAGMA foreign_keys=ON")
        self.assertEqual(restored.execute("SELECT status FROM tiq12_report_entitlements").fetchone()[0], "revoked")
        self.assertEqual(restored.execute("SELECT reason FROM tiq12_revocations").fetchone()[0], "dispute")
        with self.assertRaises(sqlite3.IntegrityError):
            restored.execute("UPDATE tiq12_report_entitlements SET status='granted', revoked_at=NULL")
        restored.close()

if __name__ == "__main__":
    unittest.main()
