"""No network, no environment credentials, no real lead records."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.verify_nija_lead_storage_readonly import audit, configured_paths, inspect_database, main


def create_db(path, table):
    with contextlib.closing(sqlite3.connect(path)) as conn:
        if table == "intake":
            conn.executescript("""CREATE TABLE website_leads (
                event_key TEXT PRIMARY KEY, form_name TEXT, email TEXT,
                submitted_at TEXT, received_at TEXT, source_payload_json TEXT);
            INSERT INTO website_leads VALUES ('synthetic-a','waitlist','synthetic@example.invalid',
                '2026-11-12T00:00:00Z','2026-11-12T00:00:01Z','{}');""")
        else:
            conn.executescript("""CREATE TABLE website_lead_forwarding (
                event_key TEXT PRIMARY KEY, state TEXT, lease_until REAL, lease_token TEXT);
            INSERT INTO website_lead_forwarding VALUES ('synthetic-a','uncertain',0,'');
            CREATE TABLE website_lead_forward_aliases (
                source_key TEXT PRIMARY KEY, legacy_key TEXT NOT NULL,
                created_at TEXT NOT NULL);""")


class ReadonlyLeadStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'persistent'
        self.root.mkdir()
        self.intake = self.root / 'intake.sqlite3'
        self.forward = self.root / 'forward.sqlite3'

    def populated(self):
        create_db(self.intake, 'intake')
        create_db(self.forward, 'forward')

    def test_known_source_default_is_not_mount(self):
        env = {}
        intake, _ = configured_paths(env)
        self.assertEqual(str(intake), '/app/data/nija_outreach.sqlite3')

    def test_explicit_env_paths_win(self):
        intake, forward = configured_paths({'NIJA_LEAD_DB_PATH':'/data/i.db', 'NIJA_LEAD_FORWARD_DB_PATH':'/data/f.db'})
        self.assertEqual((str(intake),str(forward)), ('/data/i.db','/data/f.db'))

    def test_valid_files_are_local_preflight_only_not_certification(self):
        self.populated()
        r = audit(self.intake, self.forward, self.root)
        self.assertEqual(r['local_placement_and_integrity'], 'checked')
        self.assertIs(r['production_pipeline_certified'], False)
        self.assertEqual(r['intake']['row_count'], 1)
        self.assertEqual(r['forwarding']['row_count'], 1)
        self.assertEqual(r['independent_isolated_restore'], 'UNVERIFIED_EXTERNAL_EVIDENCE_REQUIRED')
        self.assertNotIn('synthetic@example.invalid', json.dumps(r))

    def test_missing_db_is_unverified_not_zero(self):
        r = audit(self.intake, self.forward, self.root)
        self.assertEqual(r['intake']['reason'], 'database_unavailable_not_zero_rows')
        self.assertIsNone(r['intake']['row_count'])
        self.assertEqual(r['local_placement_and_integrity'], 'UNVERIFIED')
        self.assertFalse(self.intake.exists())

    def test_ephemeral_intake_path_not_certified(self):
        self.populated()
        outside = Path(self.tmp.name) / 'ephemeral.sqlite3'
        create_db(outside, 'intake')
        r = audit(outside, self.forward, self.root)
        self.assertEqual(r['intake']['reason'], 'outside_expected_persistent_root')
        self.assertEqual(r['local_placement_and_integrity'], 'UNVERIFIED')

    def test_corrupt_database_is_not_counted_as_zero(self):
        self.intake.write_bytes(b'not-sqlite')
        r = inspect_database(self.intake, self.root, 'intake')
        self.assertIsNone(r['row_count'])
        self.assertEqual(r['status'], 'UNVERIFIED')
        self.assertTrue(r['reason'].startswith('sqlite_read_failed:'))

    def test_trade_ledger_name_cannot_be_read_as_lead_storage(self):
        restricted = self.root / 'trade_ledger.db'
        create_db(restricted, 'intake')
        r = inspect_database(restricted, self.root, 'intake')
        self.assertEqual(r['reason'], 'restricted_non_lead_database')
        self.assertIsNone(r['row_count'])

    def test_symlink_rejected(self):
        self.populated()
        link = self.root / 'link.sqlite3'
        link.symlink_to(self.intake)
        r = inspect_database(link, self.root, 'intake')
        self.assertEqual(r['reason'], 'symlink_path_rejected')

    def test_missing_table_is_unverified(self):
        create_db(self.intake, 'forward')
        r = inspect_database(self.intake, self.root, 'intake')
        self.assertEqual(r['schema'], 'missing_required_table')
        self.assertIsNone(r['row_count'])

    def test_single_shared_db_requires_review(self):
        self.populated()
        r = audit(self.intake, self.intake, self.root)
        self.assertFalse(r['separate_databases'])
        self.assertEqual(r['local_placement_and_integrity'], 'UNVERIFIED')

    def test_missing_root_is_not_compliant(self):
        self.populated()
        r = audit(self.intake, self.forward, self.root / 'missing')
        self.assertEqual(r['intake']['reason'], 'expected_persistent_root_not_available')

    def test_wal_mode_requires_snapshot_without_sidecar_creation(self):
        self.populated()
        with contextlib.closing(sqlite3.connect(self.intake)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        sidecars = [Path(str(self.intake) + suffix) for suffix in ("-wal", "-shm")]
        before = [item.exists() for item in sidecars]
        r = inspect_database(self.intake, self.root, "intake")
        self.assertEqual(r["reason"], "wal_database_requires_consistent_snapshot")
        self.assertIsNone(r["row_count"])
        self.assertEqual([item.exists() for item in sidecars], before)

    def test_journal_sidecar_refuses_inspection(self):
        self.populated()
        Path(str(self.forward) + "-journal").write_bytes(b"synthetic-journal")
        r = inspect_database(self.forward, self.root, "forward")
        self.assertEqual(r["reason"], "active_sqlite_sidecar_requires_consistent_snapshot")
        self.assertIsNone(r["row_count"])

    def test_forward_alias_table_is_required(self):
        self.populated()
        with contextlib.closing(sqlite3.connect(self.forward)) as conn:
            conn.execute("DROP TABLE website_lead_forward_aliases")
            conn.commit()
        r = inspect_database(self.forward, self.root, "forward")
        self.assertEqual(r["alias_schema"], "missing_required_table")
        self.assertEqual(r["status"], "UNVERIFIED")

    def test_whitespace_override_preserves_live_precedence(self):
        intake, forward = configured_paths({
            "NIJA_LEAD_DB_PATH": "   ",
            "NIJA_OUTREACH_DB_PATH": "/data/secondary.sqlite3",
            "NIJA_LEAD_FORWARD_DB_PATH": "   ",
        })
        self.assertFalse(intake.is_absolute())
        self.assertEqual(forward, Path("/data/nija_lead_forwarding.sqlite3")
                         if Path("/data").is_dir() else intake)

    def test_immutable_read_does_not_create_sqlite_sidecars(self):
        self.populated()
        before = {str(p): p.read_bytes() for p in (self.intake, self.forward)}
        r = audit(self.intake, self.forward, self.root)
        self.assertEqual(r["local_placement_and_integrity"], "checked")
        self.assertEqual(r["forwarding"]["alias_row_count"], 0)
        for p in (self.intake, self.forward):
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(p) + suffix).exists())
        self.assertEqual(before, {str(p): p.read_bytes() for p in (self.intake, self.forward)})

    def test_readonly_execution_does_not_mutate_database(self):
        self.populated()
        before = {str(p):p.read_bytes() for p in (self.intake,self.forward)}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exit_code = main(['--intake-db',str(self.intake), '--forward-db',str(self.forward), '--expected-persistent-root',str(self.root)])
        self.assertEqual(exit_code,0)
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.intake,self.forward)})
        self.assertFalse(json.loads(out.getvalue())['production_pipeline_certified'])

    def test_missing_db_exits_nonzero_and_does_not_create(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=main(['--intake-db',str(self.intake), '--forward-db',str(self.forward), '--expected-persistent-root',str(self.root)])
        self.assertEqual(code,2)
        self.assertFalse(self.intake.exists())
        self.assertIsNone(json.loads(out.getvalue())['intake']['row_count'])


if __name__ == '__main__':
    unittest.main()
