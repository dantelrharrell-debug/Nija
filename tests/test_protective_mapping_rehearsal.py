"""Exercise schema additions on disposable databases only; no broker access."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts import nija_protective_mapping_rehearsal as rehearsal


class ProtectiveMappingRehearsalTests(unittest.TestCase):
    """Existing records and unknown protection must survive every outcome."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.backup = self.root / "closed-backup.db"
        self.candidate = self.root / "candidate.db"
        with closing(sqlite3.connect(self.backup)) as db:
            db.executescript("""
                CREATE TABLE open_positions(position_id TEXT PRIMARY KEY,user_id TEXT,status TEXT,
                    quantity REAL,entry_price REAL);
                CREATE TABLE trade_ledger(user_id TEXT,position_id TEXT,action TEXT,order_id TEXT);
                CREATE TABLE completed_trades(position_id TEXT,user_id TEXT);
                CREATE TABLE strategy_order_intents(broker TEXT,account_scope TEXT,order_id TEXT);
                CREATE TABLE pending_kraken_closes(broker TEXT,account_scope TEXT,state TEXT,order_id TEXT);
                CREATE INDEX position_user ON open_positions(user_id);
                CREATE TABLE extra_state(value BLOB);
                INSERT INTO extra_state VALUES (X'0001FF');
                INSERT INTO open_positions VALUES ('offline-position','platform','open',0.1,100);
                INSERT INTO trade_ledger VALUES ('platform','offline-position','OPEN','OABCDE-ABCDE-ABCDEF');
                INSERT INTO pending_kraken_closes VALUES ('kraken','platform:kraken','pending','OABCDE-ABCDE-ABCDEF');
            """)
        self.backup.chmod(0o600)
        self.original = self.backup.read_bytes()
        self.digest = hashlib.sha256(self.original).hexdigest()

    def run_rehearsal(self) -> dict:
        return rehearsal.prepare_candidate(self.backup, self.candidate, self.digest)

    def test_adds_nullable_columns_preserves_source_and_all_original_records(self) -> None:
        report = self.run_rehearsal()
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(report['columns_added'], list(rehearsal.MAPPING_COLUMNS))
        self.assertEqual(self.candidate.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.candidate.stat().st_nlink, 1)
        with closing(sqlite3.connect(self.candidate)) as db:
            self.assertEqual(db.execute('SELECT * FROM open_positions').fetchone(),
                             ('offline-position', 'platform', 'open', 0.1, 100, None, None))
            self.assertEqual(db.execute('SELECT state FROM pending_kraken_closes').fetchall(), [('pending',)])
            self.assertEqual(db.execute('SELECT value FROM extra_state').fetchone(), (b'\x00\x01\xff',))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        for key in ('production_apply_authorized', 'allow_new_orders', 'broker_reconciled',
                    'protective_coverage_verified', 'backup_origin_verified', 'offhost_restore_certified'):
            self.assertIs(report[key], False)
        self.assertNotIn('offline-position', str(report))

    def test_canonical_preflight_still_rejects_missing_ids_and_pending_closes(self) -> None:
        from bot.kraken_sqlite_readonly_preflight_v488 import inspect_kraken_ledger
        self.run_rehearsal()
        report = inspect_kraken_ledger(self.candidate, persistent_root=self.root)
        self.assertNotIn('exchange_protective_order_id_mapping_missing', report['issues'])
        self.assertIn('exchange_protective_order_ids_unverified', report['issues'])
        self.assertIn('pending_kraken_closes_require_reconciliation', report['issues'])
        self.assertIs(report['collector_install_allowed'], False)

    def test_repeated_rehearsal_preserves_existing_mappings(self) -> None:
        self.run_rehearsal()
        with closing(sqlite3.connect(self.candidate)) as db:
            db.execute("UPDATE open_positions SET stop_order_id='offline-stop',take_profit_order_id='offline-profit'")
            db.commit()
        destination = self.root / 'second-candidate.db'
        digest = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        report = rehearsal.prepare_candidate(self.candidate, destination, digest)
        self.assertEqual(report['columns_added'], [])
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute('SELECT stop_order_id,take_profit_order_id FROM open_positions').fetchone(),
                             ('offline-stop', 'offline-profit'))

    def test_partial_schema_adds_only_missing_field(self) -> None:
        with closing(sqlite3.connect(self.backup)) as db:
            db.execute('ALTER TABLE open_positions ADD COLUMN stop_order_id TEXT')
            db.execute("UPDATE open_positions SET stop_order_id='offline-existing'")
            db.commit()
        self.digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        self.assertEqual(self.run_rehearsal()['columns_added'], ['take_profit_order_id'])

    def test_no_overwrite_or_in_place_mode(self) -> None:
        for candidate in (self.backup,):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'new_candidate_required'):
                rehearsal.prepare_candidate(self.backup, candidate, self.digest)
        self.candidate.write_bytes(b'previous-artifact')
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'new_candidate_required'):
            self.run_rehearsal()
        self.assertEqual(self.candidate.read_bytes(), b'previous-artifact')
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_live_runtime_and_production_storage_are_refused(self) -> None:
        import os
        with patch.dict(os.environ, {'RENDER_SERVICE_ID': 'offline-test-service'}):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'isolated_review_environment_required'):
                self.run_rehearsal()
        for source, destination in ((Path('/data/closed.db'), self.candidate),
                                    (self.backup, Path('/app/candidate.db'))):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'isolated_review_environment_required'):
                rehearsal.prepare_candidate(source, destination, self.digest)
        self.assertFalse(self.candidate.exists())

    def test_digest_sidecars_permissions_and_symlinks_fail_closed(self) -> None:
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'backup_digest_mismatch'):
            rehearsal.prepare_candidate(self.backup, self.candidate, '0' * 64)
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(self.backup) + suffix)
            sidecar.touch()
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'closed_backup_without_sidecars_required'):
                self.run_rehearsal()
            sidecar.unlink()
        self.backup.chmod(0o644)
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'private_bounded_backup_required'):
            self.run_rehearsal()
        self.backup.chmod(0o600)
        alias = self.root / 'alias.db'
        alias.symlink_to(self.backup)
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'symlink_refused'):
            rehearsal.prepare_candidate(alias, self.candidate, self.digest)
        self.assertFalse(self.candidate.exists())

    def test_ddl_failure_rolls_back_and_publishes_nothing(self) -> None:
        observed = []
        def fail_after_first(db, missing):
            db.set_trace_callback(observed.append)
            db.execute('ALTER TABLE open_positions ADD COLUMN stop_order_id TEXT')
            raise rehearsal.RehearsalDenied('injected_failure')
        with patch.object(rehearsal, '_add_columns', fail_after_first):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'injected_failure'):
                self.run_rehearsal()
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(self.candidate.exists())
        self.assertFalse(list(self.root.glob('.ledger-candidate-*')))
        self.assertIn('ROLLBACK', observed)

    def test_data_change_is_rejected_without_publishing(self) -> None:
        original = rehearsal._add_columns
        def tamper(db, missing):
            original(db, missing)
            db.execute("UPDATE pending_kraken_closes SET state='reconciled'")
        with patch.object(rehearsal, '_add_columns', tamper):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'original_records_changed'):
                self.run_rehearsal()
        self.assertFalse(self.candidate.exists())
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_incompatible_column_type_and_row_budget_are_refused(self) -> None:
        with closing(sqlite3.connect(self.backup)) as db:
            db.execute('ALTER TABLE open_positions ADD COLUMN stop_order_id INTEGER')
            db.commit()
        self.digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'mapping_column_type_conflict'):
            self.run_rehearsal()
        with patch.object(rehearsal, 'MAX_ROWS', 0):
            with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'rehearsal_row_budget_exceeded'):
                self.run_rehearsal()
        self.assertFalse(self.candidate.exists())

    def test_late_destination_collision_does_not_overwrite_the_existing_file(self) -> None:
        import os
        link = os.link
        def collide(source, destination, **kwargs):
            self.candidate.write_bytes(b'concurrent-artifact')
            return link(source, destination, **kwargs)
        with patch.object(rehearsal.os, 'link', collide):
            with self.assertRaises(FileExistsError):
                self.run_rehearsal()
        self.assertEqual(self.candidate.read_bytes(), b'concurrent-artifact')
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('.ledger-candidate-*')))

    def test_stale_destination_wal_prevents_publication(self) -> None:
        sidecar = Path(str(self.candidate) + '-wal')
        sidecar.write_bytes(b'stale-wal')
        with self.assertRaisesRegex(rehearsal.RehearsalDenied, 'new_candidate_without_sidecars_required'):
            self.run_rehearsal()
        self.assertFalse(self.candidate.exists())
        self.assertEqual(sidecar.read_bytes(), b'stale-wal')
        self.assertFalse(list(self.root.glob('.ledger-candidate-*')))


if __name__ == '__main__':
    unittest.main()
