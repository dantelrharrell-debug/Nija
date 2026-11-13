"""Verify encrypted lead snapshots off-host without writing plaintext files."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

from nija_lead_protected_snapshot import logical_state


def verify(encrypted: Path, key: Path, certificate: Path, expected_sha256: str) -> dict:
    """Decrypt into memory and compare every stored schema and typed record."""
    ciphertext = encrypted.read_bytes()
    digest = hashlib.sha256(ciphertext).hexdigest()
    if digest != expected_sha256:
        raise ValueError('encrypted_checksum_mismatch')
    result = subprocess.run(
        ['openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER', '-inkey', str(key), '-recip', str(certificate)],
        input=ciphertext, capture_output=True, timeout=20, check=False,
    )
    if result.returncode:
        raise ValueError('authenticated_decryption_failed')
    databases = {}
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        expected = set(manifest['databases']) | {'manifest.json'}
        if set(archive.namelist()) != expected:
            raise ValueError('unexpected_archive_inventory')
        for name, original in manifest['databases'].items():
            if name not in ('nija_outreach.sqlite3', 'nija_lead_forwarding.sqlite3'):
                raise ValueError('nonlead_archive_entry')
            binary = archive.read(name)
            if hashlib.sha256(binary).hexdigest() != original['snapshot_sha256']:
                raise ValueError('snapshot_checksum_mismatch')
            db = sqlite3.connect(':memory:')
            try:
                db.deserialize(binary)
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('restored_integrity_failure')
                if db.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('restored_relationship_failure')
                if logical_state(db) != {k: original[k] for k in ('schema_sha256', 'tables')}:
                    raise ValueError('restored_content_mismatch')
            finally:
                db.close()
            databases[name] = {'snapshot_sha256': original['snapshot_sha256'],
                               'schema_and_all_typed_records_match': True,
                               'table_counts': {k: v['rows'] for k, v in original['tables'].items()}}
    return {'encrypted_sha256': digest, 'captured_at_unix': manifest['captured_at_unix'],
            'isolated_restore_passed': True, 'plaintext_files_written': False,
            'databases': databases, 'production_pipeline_certified': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encrypted', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--certificate', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.encrypted, args.key, args.certificate, args.expected_sha256), sort_keys=True))
        return 0
    except Exception as error:
        print('isolated_restore_failed_closed:' + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
