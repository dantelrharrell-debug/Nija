"""Isolated end-to-end tests for a filesystem-write-denied SQLite capture."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/nija_lead_protected_snapshot.py'


class ProtectedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.intake = self.root / 'nija_outreach.sqlite3'
        self.forward = self.root / 'nija_lead_forwarding.sqlite3'
        with sqlite3.connect(self.intake) as db:
            db.executescript("""CREATE TABLE website_leads(event_key TEXT PRIMARY KEY, payload BLOB, consent TEXT);
                CREATE INDEX lead_consent ON website_leads(consent);
                INSERT INTO website_leads VALUES('synthetic-a',X'0001','no sms or calls');
                INSERT INTO website_leads VALUES('synthetic-b',NULL,'email only');
                CREATE TABLE outreach_apollo_field_mappings(env_name TEXT,field_id TEXT);
                INSERT INTO outreach_apollo_field_mappings VALUES('reviewed-field','field-id');
                CREATE TABLE outreach_apollo_sync_state(singleton INT,cursor TEXT);
                INSERT INTO outreach_apollo_sync_state VALUES(1,'original-cursor');""")
        with sqlite3.connect(self.forward) as db:
            db.executescript("""CREATE TABLE website_lead_forwarding(event_key TEXT PRIMARY KEY,state TEXT);
                INSERT INTO website_lead_forwarding VALUES('synthetic-a','uncertain');
                CREATE TABLE website_lead_forward_aliases(source_key TEXT,legacy_key TEXT,created_at TEXT);
                INSERT INTO website_lead_forward_aliases VALUES('new','old','original-time');""")

    def tearDown(self):
        self.temp.cleanup()

    def run_capture(self, *args):
        return subprocess.run([sys.executable, '-B', '-S', str(SCRIPT), *map(str, args)],
                              capture_output=True, timeout=20)

    def test_isolated_restore_preserves_all_typed_records_aliases_and_indexes(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = self.run_capture('--archive-to-encryption-stdout', self.intake, self.forward)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            for path in (self.intake, self.forward):
                binary = archive.read(path.name)
                self.assertEqual(hashlib.sha256(binary).hexdigest(),
                                 manifest['databases'][path.name]['snapshot_sha256'])
                restored = sqlite3.connect(':memory:')
                restored.deserialize(binary)
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                with sqlite3.connect(path) as source:
                    schema = "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                    self.assertEqual(source.execute(schema).fetchall(), restored.execute(schema).fetchall())
                    for table in manifest['databases'][path.name]['tables']:
                        sql = 'SELECT * FROM "' + table + '"'
                        self.assertEqual(source.execute(sql).fetchall(), restored.execute(sql).fetchall())
                restored.close()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_public_summary_never_discloses_records_or_private_content_hashes(self):
        result = self.run_capture(self.intake, self.forward)
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode()
        self.assertNotIn('synthetic-a', text)
        self.assertNotIn('email only', text)
        self.assertNotIn('content_sha256_private', text)
        self.assertTrue(json.loads(text)['sandbox_write_denial_verified'])

    def test_kernel_denies_existing_file_modification_and_new_file_creation(self):
        code = """import importlib.util,sys,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('snapshot',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.deny_filesystem_writes()
for path in (sys.argv[2],sys.argv[3]):
 try: os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 except PermissionError: pass
 else: raise SystemExit(8)
print('WRITE_DENIAL_VERIFIED')
"""
        before = self.intake.read_bytes()
        result = subprocess.run([sys.executable, '-B', '-S', '-c', code, str(SCRIPT),
                                 str(self.intake), str(self.root / 'must-not-exist')], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.intake.read_bytes())
        self.assertFalse((self.root / 'must-not-exist').exists())

    def test_active_wal_and_rollback_journal_are_refused_without_sidecar_changes(self):
        with sqlite3.connect(self.intake) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("INSERT INTO website_leads VALUES('wal',NULL,'none')")
            before = {p.name: p.read_bytes() for p in self.root.iterdir()}
            result = self.run_capture(self.intake)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        journal = Path(str(self.forward) + '-journal')
        journal.write_bytes(b'protected synthetic journal')
        result = self.run_capture(self.forward)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(journal.read_bytes(), b'protected synthetic journal')

    def test_missing_symlink_and_nonlead_sources_fail_closed(self):
        alias = self.root / 'link' / self.intake.name
        alias.parent.symlink_to(self.root, target_is_directory=True)
        for path in (self.root / 'missing' / self.intake.name, alias, self.root / 'trade_ledger.db'):
            result = self.run_capture(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')

    def test_nonlead_table_is_not_exported(self):
        with sqlite3.connect(self.intake) as db:
            db.execute('CREATE TABLE trading_positions(symbol TEXT)')
        before = self.intake.read_bytes()
        result = self.run_capture('--archive-to-encryption-stdout', self.intake)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(before, self.intake.read_bytes())


if __name__ == '__main__':
    unittest.main()
