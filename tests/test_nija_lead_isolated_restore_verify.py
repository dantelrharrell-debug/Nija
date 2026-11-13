"""Authenticated encryption and isolated recovery negative controls."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from nija_lead_isolated_restore_verify import verify


class IsolatedRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.key = cls.root / 'recovery.pem'
        cls.cert = cls.root / 'public.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(cls.key), '-out', str(cls.cert), '-days', '1',
                        '-subj', '/CN=Isolated synthetic test'], capture_output=True, check=True)
        source = cls.root / 'nija_outreach.sqlite3'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE website_leads(event_key TEXT,consent TEXT)')
            db.execute("INSERT INTO website_leads VALUES('synthetic','no calls')")
        archive = subprocess.run([sys.executable, '-B', '-S', str(SCRIPTS / 'nija_lead_protected_snapshot.py'),
                                  '--archive-to-encryption-stdout', str(source)], capture_output=True, check=True).stdout
        cipher = subprocess.run(['openssl', 'cms', '-encrypt', '-binary', '-aes-256-gcm',
                                 '-outform', 'DER', str(cls.cert)], input=archive, capture_output=True, check=True).stdout
        cls.encrypted = cls.root / 'backup.p7m'
        cls.encrypted.write_bytes(cipher)
        cls.digest = hashlib.sha256(cipher).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_authentic_archive_restores_all_records_without_plaintext_files(self):
        before = set(self.root.iterdir())
        report = verify(self.encrypted, self.key, self.cert, self.digest)
        self.assertTrue(report['isolated_restore_passed'])
        self.assertFalse(report['plaintext_files_written'])
        self.assertEqual(before, set(self.root.iterdir()))
        self.assertNotIn('no calls', json.dumps(report))

    def test_wrong_expected_checksum_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'encrypted_checksum_mismatch'):
            verify(self.encrypted, self.key, self.cert, '0' * 64)

    def test_modified_ciphertext_is_refused_even_with_recomputed_checksum(self):
        damaged = bytearray(self.encrypted.read_bytes())
        damaged[-40] ^= 1
        path = self.root / 'damaged.p7m'
        path.write_bytes(damaged)
        with self.assertRaises(ValueError):
            verify(path, self.key, self.cert, hashlib.sha256(damaged).hexdigest())


if __name__ == '__main__':
    unittest.main()
