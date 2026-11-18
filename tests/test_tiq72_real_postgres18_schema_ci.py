"""Disposable PostgreSQL 18 integration tests for the TIQ v515 report ledger.

GitHub Actions only. This never connects to any NIJA Render database,
never uses customer data, and does not prove production backup recovery.
Normal test discovery skips the class unless its isolated CI gate is set.
"""
from __future__ import annotations

import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "web/trading-challenge/v515/server/sql/tiq72-v515-report-ledger.sql"
TABLES = frozenset({
    "tiq72_v515_runs",
    "tiq72_v515_reservations",
    "tiq72_v515_reports",
    "tiq72_v515_verified_events",
})
CI_DB = "nija_tiq72_ci_scratch"
CI_ROLE = "nija_tiq72_ci"


@unittest.skipUnless(
    os.environ.get("NIJA_TIQ72_CI_EPHEMERAL_POSTGRES") == "1",
    "Only runs in the explicitly enabled disposable PostgreSQL CI job",
)
class EphemeralPostgresSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fail before any connection if this is a production-like target.
        if (os.getenv("GITHUB_ACTIONS") != "true"
                or os.getenv("PGHOST") not in ("127.0.0.1", "localhost")
                or os.getenv("PGDATABASE") != CI_DB
                or os.getenv("PGUSER") != CI_ROLE
                or os.getenv("PGPORT") != "5432"):
            raise AssertionError("ephemeral_ci_identity_required")

        import psycopg2
        cls.driver = psycopg2
        cls.connection_args = {
            "host": os.environ["PGHOST"],
            "port": 5432,
            "dbname": CI_DB,
            "user": CI_ROLE,
            "connect_timeout": 8,
        }
        # PGPASSWORD is supplied only to the isolated Actions container.
        cls.bootstrap = psycopg2.connect(**cls.connection_args)
        try:
            with cls.bootstrap.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                if cursor.fetchone() != (CI_DB, CI_ROLE):
                    raise AssertionError("connected_ci_identity_mismatch")
                cursor.execute("SELECT current_setting('server_version_num')::integer")
                if cursor.fetchone()[0] // 10000 != 18:
                    raise AssertionError("postgreSQL_18_required")
            cls.bootstrap.rollback()

            sql = SCHEMA.read_text(encoding="utf-8")
            if (not sql.startswith("-- TIQ v515 test-only durable ledger.")
                    or sql.count("CREATE TABLE IF NOT EXISTS tiq72_v515_") != 4
                    or sql.count("\nBEGIN;\n") != 1
                    or sql.count("\nCOMMIT;") != 1):
                raise AssertionError("unapproved_schema_shape")

            # This disposable database is created fresh by GitHub Actions.
            # The source SQL executes its own BEGIN/COMMIT transaction.
            cls.bootstrap.set_session(autocommit=True)
            with cls.bootstrap.cursor() as cursor:
                cursor.execute(sql)
            cls.bootstrap.set_session(autocommit=False)
        except Exception:
            cls.bootstrap.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.bootstrap.close()

    def setUp(self):
        self.connection = self.driver.connect(**self.connection_args)
        self.cursor = self.connection.cursor()

    def tearDown(self):
        self.connection.rollback()
        self.cursor.close()
        self.connection.close()

    def insert_run(self, run_id="ci-run-a", attempt="ci-attempt-a"):
        self.cursor.execute(
            "INSERT INTO tiq72_v515_runs "
            "(run_id,owner_id,canonical_run,canonical_digest,attempt_key) "
            "VALUES (%s,%s,%s::jsonb,%s,%s)",
            (run_id, "ci-owner-a", "{}", "ci-digest", attempt),
        )

    def insert_reservation(self, session="cs_test_ci_synthetic"):
        self.insert_run()
        self.cursor.execute(
            "INSERT INTO tiq72_v515_reservations "
            "(reservation_id,run_id,owner_id,stripe_session) VALUES (%s,%s,%s,%s)",
            ("ci-reservation", "ci-run-a", "ci-owner-a", session),
        )

    def test_exact_four_tables_in_public(self):
        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name LIKE 'tiq72_v515_%'"
        )
        self.assertEqual({row[0] for row in self.cursor.fetchall()}, TABLES)

    def test_owner_attempt_key_is_unique(self):
        self.insert_run()
        with self.assertRaises(self.driver.errors.UniqueViolation):
            self.insert_run(run_id="ci-run-b")

    def test_live_stripe_checkout_session_is_rejected(self):
        self.insert_run()
        with self.assertRaises(self.driver.errors.CheckViolation):
            self.cursor.execute(
                "INSERT INTO tiq72_v515_reservations "
                "(reservation_id,run_id,owner_id,stripe_session) "
                "VALUES (%s,%s,%s,%s)",
                ("ci-reservation", "ci-run-a", "ci-owner-a", "cs_live_ci_synthetic"),
            )

    def test_invalid_signed_event_type_is_rejected(self):
        self.insert_reservation()
        with self.assertRaises(self.driver.errors.CheckViolation):
            self.cursor.execute(
                "INSERT INTO tiq72_v515_verified_events "
                "(event_id,event_type,reservation_id,stripe_session) "
                "VALUES (%s,%s,%s,%s)",
                ("ci-event", "invoice.paid", "ci-reservation", "cs_test_ci_synthetic"),
            )

    def test_verified_event_idempotency_is_enforced(self):
        self.insert_reservation()
        event = (
            "ci-event", "checkout.session.completed",
            "ci-reservation", "cs_test_ci_synthetic",
        )
        insert = (
            "INSERT INTO tiq72_v515_verified_events "
            "(event_id,event_type,reservation_id,stripe_session) "
            "VALUES (%s,%s,%s,%s)"
        )
        self.cursor.execute(insert, event)
        with self.assertRaises(self.driver.errors.UniqueViolation):
            self.cursor.execute(insert, event)

    def test_report_requires_matching_parent_run_and_reservation(self):
        with self.assertRaises(self.driver.errors.ForeignKeyViolation):
            self.cursor.execute(
                "INSERT INTO tiq72_v515_reports "
                "(run_id,reservation_id,owner_id,stripe_session,report) "
                "VALUES (%s,%s,%s,%s,%s::jsonb)",
                ("no-such-run", "no-such-reservation", "ci-owner-a",
                 "cs_test_ci_synthetic", "{}"),
            )

    def test_transaction_rollback_does_not_leave_a_test_run(self):
        self.insert_run()
        self.connection.rollback()
        self.cursor.execute(
            "SELECT COUNT(*) FROM tiq72_v515_runs WHERE run_id=%s",
            ("ci-run-a",),
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
